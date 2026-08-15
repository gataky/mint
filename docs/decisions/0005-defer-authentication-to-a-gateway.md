# 0005 — Defer authentication to a gateway or mesh, and reserve its slot inside logging

**Status:** accepted (2026-08-14)
**Date:** 2026-08-14
**Chunk:** [01 — Decisions and ADRs](../../tasks/01-decisions.md)

## Context

The spec defers authentication and authorization on the expectation that they
land at "a gateway or mesh, not per-service." That expectation is the load-
bearing part of this ADR — more than the deferral itself — because a template
that ships no auth is only safe if something upstream is guaranteed to have
it, and nothing in Phase 1 verifies that guarantee.

There is also a hard scheduling constraint. Chunk 06 **freezes** the
middleware chain and adds parity check #7, which diffs the chain each service
actually builds against `docs/architecture.md` and fails on any divergence.
After that, moving a middleware means amending the one artifact both languages
are validated against, in both languages, plus the document, plus the check.
So the auth slot's exact position has to be right *now*, not approximately
right.

The spec proposes, outermost first:

```
recovery → request-id → tracing → metrics → [auth: reserved] → logging → timeout → handler
```

That places auth **outside** logging, which means a request rejected as
unauthenticated produces no access-log line at all. That is the placement this
ADR interrogates.

## Decision

**1. No authentication or authorization code in Phase 1.** Not a no-op
middleware, not a `Bearer` token stub, not a config key. A named position in
the chain and a documented assumption, and nothing else.

**2. The reserved slot moves one position inward** — auth sits between
`logging` and `timeout`:

```
recovery → request-id → tracing → metrics → logging → [auth: reserved] → timeout → handler
```

This is the chain `docs/architecture.md` records and chunk 06 freezes. The
rule that generates it, stated in one line so it can be applied to any future
middleware:

> **Observe everything, then authorize, then execute.** Everything outside the
> auth slot is observational and must run for every request that reaches the
> process. Everything inside it is execution and runs only for requests
> allowed to execute.

Position by position:

| middleware | side of auth | why |
| --- | --- | --- |
| recovery | outside | A panic *in the auth middleware* must not take the process down. Auth is the most likely middleware to panic — it parses attacker-controlled input. |
| request-id | outside | A rejected caller must still get a request ID echoed back, or a user-reported 401 cannot be traced to a log line. |
| tracing | outside | A rejected request is still a span, with `http.status_code=401`. Trace-based debugging of an auth misconfiguration depends on this. |
| metrics | outside | See below — this is the security signal. |
| logging | outside | See below — this is the audit record. |
| timeout | **inside** | The configured request deadline is the *handler's* business budget. Auth is not the handler's work and must not silently consume its budget. Auth gets its own timeout when it lands, as a separate documented config key. |

**3. The assumption is recorded and made mechanical.** `docs/architecture.md`
and each generated service's AGENTS.md state, in these terms: *this service
performs no authentication; it assumes an upstream gateway, ingress, or
service mesh authenticates and authorizes every request before it arrives, and
it assumes the admin port is not routable from outside the cluster.* Chunk 06
adds one startup log line — emitted at WARN, once, when `ENV != local` and no
auth middleware is registered:

```
no authentication middleware is configured; this service assumes an upstream
gateway or mesh enforces authN/authZ (see docs/decisions/0005-...)
```

That single line is the only mechanical trace the deferral leaves in a running
system, and it is what turns "we assumed a gateway" from a document nobody
reads into something that appears in every production boot log and can be
alerted on. It is a deliberate, named addition to chunk 06's scope.

## Alternatives considered

### On deferring at all

**Ship a pluggable auth middleware with a no-op default.** The most obvious
alternative and the one most templates pick. Rejected for two reasons. First,
an auth interface designed before a single real auth requirement exists will
be wrong in the specific way that is expensive: the shape of the "principal"
it produces (JWT claims? mTLS SPIFFE ID? an opaque session?) determines what
the service layer can do with it, and guessing it wrongly is worse than having
nothing, because the wrong abstraction gets built on. Second — the same
argument as ADR 0006 — a shipped-but-unused code path in a template is
inherited, maintained, and documented by every generated service forever, and
its no-op default guarantees nobody notices when it breaks.

**Ship a real JWT-validating middleware, disabled by config.** Worse: a
security control whose default is "off" and whose on-path is exercised by
nobody is a security control that will be wrong the first time someone turns
it on. It also imports a JWT library into every generated service's dependency
graph in violation of the spec's "justify every dependency" rule.

**Defer with no reserved slot; add auth wherever it fits later.** This is what
the spec's deferral table exists to prevent, and correctly so. Parity check #7
compares the chain against the document; inserting a middleware later is
therefore a coordinated edit to two languages, one document, and one check, on
a deadline, under whatever pressure caused auth to become urgent. Naming the
slot now costs one line in a document.

### On the slot's position — the part with real arguments on both sides

**Auth outside metrics (metrics only sees authenticated traffic).** The
argument for it is genuine: a flood of unauthenticated requests inflates
request-rate SLIs and pollutes the latency histogram. And it pollutes it in
the worst direction — 401s are fast, so they *deflate* p99 and hide real
handler latency behind a wall of cheap rejections.

It loses anyway. If auth is outside metrics, the rate of rejected requests is
invisible to Prometheus, and the 401 rate is the single cheapest security
signal a service has: it is how credential stuffing, an expired client
credential, a misrouted caller, and a botched gateway config all announce
themselves. Losing it to protect a latency histogram is a bad trade, and the
histogram problem has a standard fix — the default instrumentation labels by
status, so `histogram_quantile` filtered to `status=~"2.."` recovers the clean
signal. A mesh makes the same choice: Envoy counts at the listener, before its
own authn filter decides anything.

**Auth outside logging (the spec's placement — rejected requests are not
logged).** The argument for it is also genuine, and it is a cost argument: log
volume is billed, and an unauthenticated flood against a service with an open
port lets an attacker drive the log bill directly. Auth outside logging caps
that.

It loses, and this is the recommendation that changes the spec. An access log
that omits rejected requests is not an access log; it is a success log. When
the 401 metric spikes, the very next question is "from where, to what path,
with what client ID" — and if the logging middleware never ran, that question
has no answer anywhere in the system. Every reverse proxy, every mesh sidecar,
and every web server in existence logs 401s; audit requirements generally
assume it. It also preserves an invariant worth having explicitly:

> **Every request that reaches the process produces exactly one access-log
> line and exactly one metrics observation.**

That invariant is what makes log-derived and metric-derived request counts
reconcilable, and it is trivially testable — which matters, because the spec
demands mechanical guarantees rather than aspirational ones. The log-volume
objection is real but is the wrong control at the wrong layer: the answer to a
flood is rate limiting at the edge and sampling in the logger, both of which
exist independently of where auth sits.

One argument for the spec's placement that turns out *not* to hold, and is
worth recording so it is not re-litigated: "auth must be outside logging so
the log line can carry the authenticated principal." It does not follow. The
logging middleware emits its line *after* the inner chain returns, because it
needs the status and duration; so an auth middleware nested inside it can
write the principal into the request context and the logger will pick it up at
emit time. Nesting auth inside logging costs nothing here.

**Auth inside timeout (auth shares the handler's request deadline).** Tempting
for safety — it guarantees a hung JWKS fetch cannot pin a request open
forever. Rejected because it makes the configured request timeout mean two
different things depending on how expensive auth happens to be that second: a
slow JWKS refresh silently shrinks every handler's budget, and the symptom
surfaces as unexplained handler timeouts. Auth outside `timeout` keeps the
config key honest, at the cost of requiring auth to bring its own timeout —
which this ADR makes an explicit requirement on whoever implements it, rather
than an accident.

## Consequences

**The risk this creates, stated without hedging.** A generated service
deployed with nothing in front of it is fully open. Every operation in the
registry is callable by anyone who can reach `port`, including any mutating
operation. `/metrics` on the admin port leaks the full route inventory,
request rates, and error rates to any caller who can reach it, and `/readyz`
enumerates dependency names. Mint ships no control that prevents this and no
check that detects it — the WARN line above announces it, but nothing refuses
to start. Anyone deploying a generated service to a network where "reachable"
and "authorized" are not the same set is responsible for closing that gap
themselves; ADR 0008's port split narrows the API surface exposed through an
ingress but is explicitly **not** a security boundary and does not help here.

The Phase 3 seam for this is a default-deny NetworkPolicy shipped with the
Kubernetes manifests, plus the gateway/mesh configuration that this ADR
assumes exists. That is the point at which the assumption stops being an
assumption, and it should be the first thing Phase 3 does rather than the
last.

**A gateway does not cover every transport.** If ADR 0004's MCP transport is
ever added over stdio, there is no gateway in the path at all — MCP has its
own OAuth-based authorization model precisely because of this. The reserved
slot in the HTTP chain does not extend to a transport that has no HTTP chain,
which is the same seam thinness ADR 0004 records. Whoever adds MCP inherits
this ADR's question again from scratch.

**What this makes easy.** Adding auth later is: one middleware constructed in
the composition root, inserted at the named position; one config section; one
column in `internal/apierror/`'s mapping table for the unauthenticated and
forbidden categories; one line changed in `docs/architecture.md` (removing the
word "reserved"). No other middleware moves, so parity check #7 keeps passing
without being rewritten, and no existing test changes.

**What this makes hard.** The chain is frozen after chunk 06, so a *second*
reserved concern discovered later (rate limiting is the obvious candidate, and
it plausibly belongs outside auth) will not have a slot and will require the
amendment this ADR was written to avoid. That is accepted: reserving slots
speculatively for things nobody has asked for is how a middleware chain
becomes eight no-ops.

**What would reverse this.** A generated service being deployed to a network
where an unauthenticated caller can reach it — at which point auth stops being
a gateway concern and becomes a Phase 1 gap, and this ADR should be superseded
rather than edited.

**Deviation from the spec, called out explicitly for approval.** The spec's
chain places auth between `metrics` and `logging`. This ADR moves it one slot
inward, between `logging` and `timeout`. `docs/architecture.md` and chunk 06
should carry the revised chain. If that move is rejected, the consequence to
accept knowingly is that rejected requests will not appear in the access log.
