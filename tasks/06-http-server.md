# 06 — HTTP server, middleware, lifecycle, health

**Spec:** § Architecture rules → Middleware order, § Health endpoints,
§ Runtime lifecycle
**Depends on:** 04, 05; ADR 0005 (auth slot), ADR 0008 (port strategy)
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

2. **The middleware chain**, exactly this order, outermost first:

   ```
   recovery → request-id → tracing → metrics → [auth: reserved] → logging → timeout → handler
   ```

   Tracing and metrics are **no-op placeholders in this chunk** with the real
   implementations landing in chunk 08 — but their positions in the chain are
   fixed now and parity-checked. The `auth` slot is named and empty per ADR
   0005.

3. **Recovery** outermost: catches a panic/unhandled exception anywhere
   inside, logs at error with trace ID and stack, returns the `problem+json`
   500 from chunk 05. The process must survive.

4. **Request ID**: accept an inbound header if present, generate one if not,
   put it in the log context and echo it on the response.

5. **Logging middleware**: one line per request with method, route template
   (never the concrete path), status, duration, and request ID. Route
   template, not concrete path — the same rule as metric labels.

6. **Timeout middleware**: per-request context deadline from config,
   propagated downward so a slow dependency can't pin a request open.

7. **Server timeouts** from config with non-zero defaults: read-header,
   read, write, idle. Go's `http.Server` with a zero `ReadHeaderTimeout` is
   both a lint failure and a slowloris vector.

8. **Health check registry**: components register a named check with its own
   timeout and a required/optional flag. `/readyz` runs them and fails only
   on required ones; the response body lists every check and its status
   either way. `/healthz` touches nothing — ever.

9. **Graceful shutdown** on SIGTERM/SIGINT: stop accepting, drain in-flight
   up to a configurable timeout, flush the tracer provider, close the
   logger. Non-zero exit if the drain times out.

10. **Startup ordering**: config → logging → tracing/metrics → repositories →
    health registration → listeners. Fail fast and loudly at each step, with
    the failure logged in the configured format.

11. **`docs/architecture.md`** — write the middleware order section (with the
    reserved auth slot explained) and the lifecycle section.

12. **Expose the chain for verification.** The parity check needs to compare
    the actual chain against `docs/architecture.md` — give each middleware a
    name and expose the ordered list somewhere a test can read it. A
    constant the chain is built from is enough; it does not need to be an
    endpoint.

## Out of scope

Business routes, the operation registry, `/openapi.json`, `/llms.txt` (chunk
07 and 09). Real tracing and metrics implementations (chunk 08) — placeholders
only, in their final positions.

## Deliverables

- `internal/transport/http/` with server, middleware chain, health endpoints
- Health check registry
- Lifecycle/shutdown in the composition root
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
- SIGTERM drains in-flight requests, then exits 0. A request that outlives
  the drain timeout produces a non-zero exit.
- `admin_port == port` collapses cleanly onto one listener, tested.
- Request logs carry the route template, never a concrete path with an ID
  in it.
- `scripts/parity.sh` gains check #7 — actual middleware order in both
  services diffed against `docs/architecture.md` — and **fails** when you
  reorder one language's chain. Demonstrate, then revert.
- `scripts/verify-template.sh` grows to cover `/healthz`, `/readyz`, and a
  SIGTERM drain assertion.

## Flag back before finishing

- Any difference in how Go and Python express the chain that makes the
  parity check awkward — FastAPI middleware ordering semantics are inverted
  relative to a hand-rolled Go chain, and if that can't be normalized
  cleanly, say so rather than fudging the comparison.
- Whether the timeout middleware belongs inside or outside logging; the spec
  fixes it inside, but if that means slow requests log the wrong duration,
  raise it.
