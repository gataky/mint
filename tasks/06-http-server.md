# 06 — HTTP server, middleware, lifecycle, health

**Spec:** § Architecture rules → Middleware order, § Health endpoints,
§ Runtime lifecycle
**Depends on:** 04, 05. **ADRs 0005 (auth slot — the chain order changed) and
0008 (port strategy, and a verified uvicorn signal race) are binding here**;
0004 fixes the transport directory boundary; 0010 fixes the access-log line.
**Size:** L
**Standing rules:** [tasks/README.md](README.md#standing-rules--these-apply-to-every-chunk)

## Goal

A generated service becomes a real server: two listeners, the frozen
middleware chain, health endpoints backed by a registry, and a shutdown that
drains cleanly. No business routes yet — those arrive with the operation
registry in chunk 07.

## Do

1. **Two listeners** per ADR 0008: the API port and the admin port
   (`/metrics`, `/healthz`, `/readyz`). Setting `admin_port == port`
   collapses them onto one listener — support and test that path.

   **Build both listeners from one slice**, in both languages: one
   construction loop, one timeout config block applied to every server, one
   drain loop with a shared deadline. "Two shutdown paths" is an
   implementation choice, not a consequence of the split.

   **Reframe why the split exists**, in `docs/architecture.md` and the
   generated README, in these words:

   > The admin port is a **routing and lifecycle** boundary, not a security
   > boundary. It exists so an ingress or Service can expose exactly one
   > port, and so readiness and metrics remain answerable while the API
   > listener is draining. It does not protect `/metrics` from anything;
   > that is NetworkPolicy's job.

   Any pod that can reach the pod IP can reach every container port on it.
   Do not let the usual "it keeps `/metrics` private" justification into the
   docs — it is false, and inheriting it is worse than inheriting nothing.

2. **The middleware chain**, exactly this order, outermost first:

   ```
   recovery → request-id → tracing → metrics → logging → [auth: reserved] → timeout → handler
   ```

   **This is not the order in the spec.** ADR 0005 moved the auth slot one
   position inward, from outside `logging` to between `logging` and
   `timeout`, and the human approved it. The rule that generates the order,
   which is what any future middleware gets placed by:

   > **Observe everything, then authorize, then execute.** Everything outside
   > the auth slot is observational and must run for every request that
   > reaches the process. Everything inside it is execution and runs only for
   > requests allowed to execute.

   The consequence that motivated the move: with auth outside `logging`, a
   request rejected as unauthenticated produces no access-log line at all,
   and "the 401 rate spiked — from where, to what path, with what client ID"
   has no answer anywhere in the system. It also preserves an invariant worth
   testing directly:

   > **Every request that reaches the process produces exactly one
   > access-log line and exactly one metrics observation.**

   Tracing and metrics are **no-op placeholders in this chunk** with the real
   implementations landing in chunk 08 — but their positions in the chain are
   fixed now and parity-checked. The `auth` slot is named and **empty**: no
   no-op middleware, no `Bearer` stub, no config key. A named position and a
   documented assumption, and nothing else.

3. **The deferred-auth warning line.** Emit once at startup, at WARN, when
   `MINT_ENV != local` and no auth middleware is registered:

   ```
   no authentication middleware is configured; this service assumes an upstream
   gateway or mesh enforces authN/authZ (see docs/decisions/0005-...)
   ```

   This is a deliberate, named addition to this chunk's scope (ADR 0005 § 3).
   It is the only mechanical trace the deferral leaves in a running system,
   and it is what makes "we assumed a gateway" something that appears in
   every production boot log and can be alerted on.

4. **Recovery** outermost: catches a panic/unhandled exception anywhere
   inside, logs at error with trace ID and stack, returns the `problem+json`
   500 from chunk 05. The process must survive. It is outermost specifically
   so that a panic in the future auth middleware — the one most likely to
   panic, since it parses attacker-controlled input — cannot take the process
   down.

5. **Request ID**: accept an inbound header if present, generate one if not,
   put it in the log context and echo it on the response. Python binds it
   with `structlog.contextvars.bind_contextvars(request_id=…)`, which ADR
   0010's spike verified survives into the endpoint through
   `BaseHTTPMiddleware`.

6. **Logging middleware**: one `http_request` line per request with method,
   route template (never the concrete path), status, duration, client IP, and
   request ID. Route template, not concrete path — the same rule as metric
   labels, and the cardinality argument applies to logs too.

   This line **replaces** uvicorn's access log, which chunk 04 disabled with
   `access_log=False`. If it isn't emitted, the Python service has no access
   log at all.

7. **Timeout middleware**, innermost: per-request context deadline from
   config, propagated downward so a slow dependency can't pin a request open.
   It sits **inside** the auth slot deliberately — the configured request
   deadline is the *handler's* business budget, and auth must not silently
   consume it. Whoever adds auth brings their own timeout as a separate
   documented config key; ADR 0005 makes that an explicit requirement rather
   than an accident.

8. **Server timeouts** from config with non-zero defaults: read-header,
   read, write, idle. Go's `http.Server` with a zero `ReadHeaderTimeout` is
   both a lint failure and a slowloris vector. One timeout block, applied to
   every server in the slice.

9. **Health check registry**: components register a named check with its own
   timeout and a required/optional flag. `/readyz` runs them and fails only
   on required ones; the response body lists every check and its status
   either way. `/healthz` touches nothing — ever.

10. **Graceful shutdown** on SIGTERM/SIGINT, in this sequence: **flip
    `/readyz` to failing first**, let the endpoints controller notice, *then*
    stop accepting on the API listener, drain in-flight up to a configurable
    timeout, flush the tracer provider, close the logger. Non-zero exit if
    the drain times out.

    The ordering is the whole operational argument for the port split: under
    the split, a mid-drain `GET /readyz` on the admin port answers `503
    "draining"`; collapsed, it answers `connection refused`. Both are treated
    as a failed probe, so collapsed is not *broken* — but it cannot report a
    meaningful readiness body or serve a final metrics scrape during the
    seconds you most want them.

11. **Python owns its own signals.** `uvicorn.Server.serve()` wraps itself in
    `capture_signals()`, which installs process-global handlers. **Two
    uvicorn servers in one process means the second registration replaces the
    first, and the measured result under SIGTERM is `EXIT=143` — the process
    dies before either server drains.** The Go twin drains cleanly under
    identical conditions, which makes this exactly the class of bug the
    parity harness exists to catch.

    Mitigation is one line per server, with a comment naming ADR 0008:

    ```python
    server.capture_signals = contextlib.nullcontext   # lifecycle is ours, not uvicorn's
    ```

    The composition root owns SIGTERM/SIGINT. This line has no local symptom
    when deleted — it only manifests under SIGTERM with two listeners — so
    the verify assertion below is its only backstop.

    **This replaces chunk 04's `uvicorn.run(...)` call.** `run()` builds and
    runs one server internally and hands you nothing to set
    `capture_signals` on, so `__main__.py` moves to explicit
    `uvicorn.Config` + `uvicorn.Server` per listener. Carry ADR 0010's
    `log_config=None` and `access_log=False` across as `Config` arguments —
    losing either one silently restores uvicorn's own log handlers and the
    service ships two log formats again.

12. **Startup ordering**: config → logging → tracing/metrics → repositories →
    health registration → listeners. Fail fast and loudly at each step, with
    the failure logged in the configured format.

13. **`internal/transport/http/` is the only place that may import
    `net/http` or FastAPI request types** (ADR 0004 invariant 1). Chunk 02
    created the nesting; state the rule in `docs/architecture.md` and AGENTS.md
    here, since this is the chunk that fills the directory.

14. **`docs/architecture.md`** — write the middleware order section (with the
    reserved auth slot, the "observe, then authorize, then execute" rule, and
    the one-log-line-one-metric invariant), the lifecycle section, and the
    admin-port reframing from item 1. Also state, in these terms: *this
    service performs no authentication; it assumes an upstream gateway,
    ingress, or service mesh authenticates and authorizes every request
    before it arrives, and it assumes the admin port is not routable from
    outside the cluster.* Same sentence in each generated service's AGENTS.md.

15. **Expose the chain for verification.** The parity check needs to compare
    the actual chain against `docs/architecture.md` — give each middleware a
    name and expose the ordered list somewhere a test can read it. A
    constant the chain is built from is enough; it does not need to be an
    endpoint.

## Out of scope

Business routes, the operation registry, `/openapi.json`, `/llms.txt` (chunk
07 and 09). Real tracing and metrics implementations (chunk 08) — placeholders
only, in their final positions. Any auth code whatsoever, including a no-op.

## Deliverables

- `internal/transport/http/` with server, middleware chain, health endpoints
- Health check registry
- Lifecycle/shutdown in the composition root, owning signals in both languages
- Middleware order + lifecycle sections of `docs/architecture.md`
- Tests in both languages

## Acceptance criteria

- `curl /healthz` on the admin port returns 200 without touching any
  dependency; `/readyz` returns 200 with an empty check list and a body that
  shows the (empty) set.
- A registered failing **required** check makes `/readyz` return 503 and
  lists it; a failing **optional** check leaves `/readyz` at 200 and still
  lists it.
- A handler that panics returns `problem+json` 500 and the process stays up.
- A request that exceeds the configured timeout returns the correct
  `problem+json` category, and the deadline is visible to downstream code.
- **SIGTERM against the split configuration drains in-flight requests, then
  exits 0** — in both languages. A request that outlives the drain timeout
  produces a non-zero exit. Delete the `capture_signals` line from the Python
  template and this test must fail with exit 143. Demonstrate, then revert.
- Mid-drain, `GET /readyz` on the admin port returns 503 with a body saying
  it is draining — not a connection refusal.
- `admin_port == port` collapses cleanly onto one listener, tested. The
  SIGTERM assertion in `scripts/verify-template.sh` runs against the
  **split** configuration; the collapsed one hides the bug and must not be
  substituted for convenience.
- The middleware chain, read from the exposed constant, is exactly
  `recovery, request-id, tracing, metrics, logging, auth, timeout` in both
  languages.
- A request that would be rejected by a future auth middleware still produces
  an access-log line and a metrics observation — assert the invariant by
  registering a stub that short-circuits at the auth position in a test, not
  by shipping one.
- The deferred-auth WARN line appears exactly once at startup when
  `MINT_ENV=prod`, and not at all when `MINT_ENV=local`.
- Request logs carry the route template, never a concrete path with an ID
  in it.
- `scripts/parity.sh` gains check #7 — actual middleware order in both
  services diffed against `docs/architecture.md` — and **fails** when you
  reorder one language's chain. Demonstrate, then revert.
- `scripts/verify-template.sh` grows to cover `/healthz`, `/readyz`, and the
  SIGTERM drain assertion, probing **both** ports.

## Flag back before finishing

- Any difference in how Go and Python express the chain that makes the
  parity check awkward — FastAPI middleware ordering semantics are inverted
  relative to a hand-rolled Go chain, and if that can't be normalized
  cleanly, say so rather than fudging the comparison.
- Anything that made you want a *second* reserved slot. ADR 0005 accepts
  that the chain is frozen after this chunk and that a later concern (rate
  limiting is the obvious candidate) will need a real amendment — but if you
  can see one coming now, this is the last cheap moment to say so.

*Settled, do not re-open:* the chain order, including auth sitting between
`logging` and `timeout` and `timeout` being innermost (ADR 0005, approved —
the spec's order is superseded). The port split and its collapse path
(ADR 0008, approved).
