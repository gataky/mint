# 0008 — Serve the API and the admin endpoints on separate ports by default

**Status:** accepted (2026-08-14)
**Date:** 2026-08-14
**Chunk:** [01 — Decisions and ADRs](../../tasks/01-decisions.md)

## Context

The spec defaults to two listeners: `port` for the API, and `admin_port`
(defaulting to `port + 1000`) for `/metrics`, `/healthz`, and `/readyz`, with
`admin_port == port` collapsing everything onto one listener. The spec itself
flags this as a decision to interrogate rather than inherit, and it is
upstream of chunk 02's question set and chunk 06's server construction.

The usual justification for the split is that it keeps `/metrics` private.
That justification is wrong, and it is worth saying so before defending the
split on other grounds.

**A separate port is not a security boundary inside a cluster.** Any pod that
can reach the pod IP can reach *every* container port on it; Kubernetes
Services do not restrict this, they only provide a name and a load-balanced
VIP for one of them. The controls that actually keep `/metrics` private are
NetworkPolicy, mesh mTLS/authorization, and — if you want it at the endpoint —
authentication on the metrics handler itself. The ecosystem has already
concluded this: kubebuilder's controller-runtime, which pioneered the
separate-metrics-port pattern, now defaults `--metrics-bind-address` to `0`
(off) and recommends `:8443` behind an authn/authz filter when it is on. The
port split was never the protection.

So the split rests on a narrower and more honest deployment assumption:

> There is an ingress, Service, or load balancer in front of the pod that
> forwards **only** `port`, and the admin port is reachable only from inside
> the cluster — by kubelet for probes and by Prometheus for scrapes.

That assumption is routinely true and cheap to satisfy: a Service lists the
ports it exposes, and omitting `admin` from it means no cluster-internal
client can reach admin *through the Service name*, and no ingress can route to
it. It is false under `hostNetwork: true`, under a LoadBalancer that forwards
all container ports, and on a bare VM with a public IP — and in those cases
the split buys nothing at all.

### What the spikes measured

**Two objections to the split turn out to be cheaper than they sound.**

*"A k8s liveness probe must target a different port than the Service."* True,
and it costs nothing. Kubelet dials the pod IP directly and never goes through
a Service; the probe's `httpGet.port` may be any container port, by number or
by name, and does not need to appear in any Service. Probes work even when no
Service selects the pod at all.

*"Two listeners means two shutdown paths and two sets of server timeouts."*
Only if you write it that way. Built as a slice of servers, shutdown is one
loop, and the collapse branch is a handful of lines. Verified in both
languages:

```
--- split: two listeners ---                --- collapsed: admin_port == port ---
api    /widgets  -> 200                     api    /widgets  -> 200
api    /healthz  -> 404                     api    /healthz  -> 200
admin  /healthz  -> 200                     api    /metrics  -> 200
admin  /metrics  -> 200                     shutdown ok (listeners=1)
shutdown ok (listeners=2)
```

**One objection is real, and it is Python-specific.** `uvicorn.Server.serve()`
wraps itself in `capture_signals()`, which installs process-global handlers
via `signal.signal(...)`. Two `uvicorn.Server` instances in one process means
the second registration replaces the first, and on exit uvicorn re-raises the
captured signal, which reaches the now-restored default handler. The result,
measured:

```
$ python signals.py     # two uvicorn servers, naive wiring, SIGTERM
EXIT=143   # 128 + SIGTERM: the process died before either server drained
```

That is precisely the class of bug `make parity` exists to catch — the Go twin
drains cleanly under identical conditions. The mitigation is one line per
server, with the composition root taking ownership of signals:

```python
server.capture_signals = contextlib.nullcontext   # lifecycle is ours, not uvicorn's
```

```
api    drained=True
admin  drained=True
drained cleanly: True     EXIT=0
```

**And one argument *for* the split turns out to be much stronger than the
privacy argument it usually gets defended with.** During graceful shutdown the
correct sequence is: flip `/readyz` to failing, let the endpoints controller
remove the pod, then drain the API. If admin and API share a listener, calling
`Shutdown()` stops serving `/readyz` too. Measured mid-drain, with an
in-flight request still running:

```
split      mid-drain GET /readyz -> 503 "draining"
collapsed  mid-drain GET /readyz -> ERR dial tcp 127.0.0.1:63629: connect: connection refused
```

Connection-refused is *treated* as a failed probe, so a collapsed service is
not broken — but it cannot report a meaningful readiness body during drain,
and Prometheus cannot scrape `/metrics` for the final seconds of the pod's
life, which are exactly the seconds you want when investigating a bad
deploy. That is an operational argument that does not depend on the security
claim at all, and it survives the security claim being false.

## Decision

**Keep the split as the default.** `port` serves the API; `admin_port`
defaults to `port + 1000` and serves `/metrics`, `/healthz`, `/readyz`.
Setting `admin_port == port` collapses both onto a single listener, and that
path is supported, documented in the question's help text, and tested.

**Reframe what the split is for, in `docs/architecture.md` and the generated
README**, so nobody inherits the wrong reason:

> The admin port is a **routing and lifecycle** boundary, not a security
> boundary. It exists so an ingress or Service can expose exactly one port,
> and so readiness and metrics remain answerable while the API listener is
> draining. It does not protect `/metrics` from anything; that is
> NetworkPolicy's job, and Phase 3 ships a default-deny policy.

**Build both listeners from one slice** in both languages — one construction
loop, one timeout config block applied to every server, one drain loop with a
shared deadline. "Two shutdown paths" is an implementation choice, not a
consequence of the split, and the parity check compares the drain behaviour of
both languages under SIGTERM.

**The Python template neutralises uvicorn's signal capture** and owns
SIGTERM/SIGINT in the composition root, with a comment naming this ADR. Chunk
06's SIGTERM drain assertion in `scripts/verify-template.sh` must run against
the *split* configuration, since that is the one where the bug appears; the
collapsed configuration hides it.

## Alternatives considered

**Single listener by default; no `admin_port` question.** The simplest option
and a real contender: one listener, one set of timeouts, one drain, six copier
questions instead of seven, `curl localhost:8080/healthz` just works, and the
whole class of two-listener bugs above never exists. It also loses nothing on
security, since the split never provided any.

It lost on two counts. First, the drain-visibility measurement above: with one
listener you cannot serve a readiness body or a metrics scrape during drain,
and there is no configuration that recovers it. Second, the default is the
thing every service inherits, and a service that starts life exposing
`/metrics` on its public API port has an exposure that is easy to create and
tedious to retract — retracting it later is a change to the ingress, the
Service, the probe definitions, and the ServiceMonitor, coordinated across
however many services made the same choice. The reverse mistake is cheap:
a service that wants one listener sets `admin_port = port` at generation time
and is done.

**Three ports, kubebuilder-style** (`8080` API, metrics, health separately).
This is what controller-runtime actually does, and kube-proxy separates
healthz (10256) from metrics (10249) too, so there is precedent. Rejected:
the reason those projects split health from metrics is that their metrics
endpoint is authenticated and their health endpoint must not be, which is a
Phase-4-at-the-earliest concern here. Three listeners triples the
configuration surface for a distinction Mint cannot yet act on.

**One listener, with the admin routes bound to loopback.** Superficially the
best of both — one port, admin unreachable from outside the pod. Fatally
broken for the actual deployment target: kubelet dials the **pod IP**, not
`127.0.0.1`, so every liveness and readiness probe fails immediately.
Prometheus cannot reach it either. Rejected on a factual error, not a trade.

**One listener, with `/metrics` and the health endpoints behind auth.** The
control that would genuinely make metrics private. Rejected for Phase 1
because ADR 0005 defers all authentication, and building auth for exactly one
endpoint would contradict that ADR's reasoning about speculative auth
abstractions. Worth revisiting when auth lands: at that point the split
becomes a lifecycle convenience only, which is what this ADR already says it
is.

**Split, but default `admin_port` to a fixed value (e.g. 9090) rather than
`port + 1000`.** A fixed default makes every generated service's admin port
identical, which is convenient for a shared ServiceMonitor and for developer
muscle memory. Rejected because it collides the moment two services run on one
developer machine, which is exactly when local port arithmetic matters most.
`port + 1000` keeps the two ports of a service memorably paired and keeps
services distinct from each other.

## Consequences

**What changes in the copier question set — this decision, kept.** The
question set stays at seven, with `admin_port` as specified, plus two
validator requirements that the spec's range check alone does not cover:

- `admin_port` must be in 1024–65535 and may equal `port` (the documented
  collapse) or differ from it. Nothing else is special-cased.
- The derived default `port + 1000` is invalid when `port > 64535`. The
  default expression must clamp or the validator must reject it with a message
  that says so, rather than producing a service that fails to bind at runtime.
  The spec requires bad input to fail at prompt time, not at boot time, and
  this is the one case where the *default* can be the bad input.
- The help text states the collapse behaviour and states that the admin port
  is not a security boundary — the same sentence as `docs/architecture.md`, so
  the reason travels with the question.

**What would have changed had the single listener won.** `admin_port` would be
dropped entirely, the question set would be six, parity check #1 would be
correspondingly smaller, and chunk 06 would have one listener and one drain.
Adding it back later would be an *additive* template change rather than a
breaking one — a new question with a derivable default — so that direction is
recoverable via `copier update`. The irrecoverable part is the deployed
surface: services generated in the single-listener era would already be
serving `/metrics` on their API port, and moving it is a coordinated
infrastructure change per service. That asymmetry is the deciding factor.

**What this makes hard.** Local development is slightly worse forever:
`/healthz` is not on the port you just curled, and every developer learns this
the same way. `--print-config` and the README must make both ports obvious.
The verify script has to probe two ports. And the Python signal-handling
landmine above is now a permanent hazard in the template — mitigated by one
line and a comment, but a line that a future refactor can delete without any
local symptom, since it only manifests under SIGTERM with two listeners. The
verify script's SIGTERM assertion is the backstop, and it must not be
downgraded to the collapsed configuration for convenience.

**What would reverse this.** Evidence from real deployments that nobody uses
the admin port as intended — that every Service exposes both, or that every
team collapses them — would make the split pure cost. That is a Phase 3
observation, and the collapse path existing from day one is what makes the
reversal cheap when it comes.
