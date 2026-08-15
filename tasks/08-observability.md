# 08 — Tracing and metrics

**Spec:** § Tracing, § Metrics
**Depends on:** 07; ADR 0003 (metric naming)
**Size:** M
**Standing rules:** [tasks/README.md](README.md#standing-rules--these-apply-to-every-chunk)

## Goal

Fill in the two middleware placeholders chunk 06 left in the chain. Traces
propagate through all three layers, the three default metrics appear on every
route with no per-handler code, and `make run` on a laptop with no Jaeger is
completely quiet.

## Do

### Tracing

1. **OpenTelemetry**, not OpenTracing. Provider setup lives in
   `internal/observability` and nowhere else — that isolation is what makes
   swapping to a Collector later a config change.

2. **Quiet local default.** When `ENV=local` and no OTLP endpoint is
   configured, install a **no-op exporter** (stdout behind an explicit
   flag). A fresh `make run` must not emit a single connection-refused
   retry. Configuring an endpoint is what opts you into real export.

3. **OTLP to Jaeger** when an endpoint *is* configured, endpoint read
   through the normal config system, `localhost:4317` as the conventional
   local value.

4. **Auto-instrument the transport.** Every inbound request starts or joins
   a span, with zero per-handler boilerplate. Span names use the route
   template, never the concrete path.

5. **Propagate through service and repository layers** — `context.Context`
   in Go, the equivalent in Python. A repository call must appear as a child
   span of its request.

6. **Flush on shutdown.** Wire the provider flush into the drain sequence
   chunk 06 built. Spans from final requests are silently lost otherwise —
   this is the single most common OTel bug, and the verify script must
   assert against it.

7. **Log correlation closes the loop.** Chunk 04 built the logger to read
   `trace_id`/`span_id` from the active span context. With a real provider
   installed they should now appear with no logging changes. Verify that
   they do — if the logger needs a change here, chunk 04's integration was
   wrong.

### Metrics

8. **`/metrics` on the admin port**, Prometheus format.

9. **Three defaults on every route, no per-handler code**: request count,
   request duration histogram, in-flight requests. Naming per ADR 0003.

10. **Cardinality guardrail, enforced in the instrumentation** — route
    labels use the registered template (`/widgets/{id}`), never the concrete
    path. This is the same rule as request logging; enforce it in code, not
    in a doc.

11. **Standard label set** per ADR 0003, including whether `service_owner`
    is a label.

12. **`docs/architecture.md`** — note where the observability wiring lives
    and why it's isolated. Record the cardinality rule in AGENTS.md
    (rendered from `docs/agents.md`) as a "don't do this" boundary.

## Out of scope

Alerting, dashboards, exemplars, custom business metrics beyond the three
defaults, OTel Collector configuration, log shipping.

## Deliverables

- Real tracing and metrics filling the chain positions from chunk 06
- `internal/observability` in both templates, with tests
- `/metrics` on the admin port in both

## Acceptance criteria

- `make run` with no Jaeger running and no endpoint configured produces
  **zero** exporter errors or retries in either language.
- With an endpoint configured, a request produces a trace with a transport
  span and a child repository span, in both languages, with matching span
  names and attribute keys.
- Log lines emitted during a traced request carry `trace_id` and `span_id`
  matching the span — and still omit them entirely outside a trace.
- SIGTERM during an in-flight request results in that request's span being
  exported. Assert this in `scripts/verify-template.sh`; it's the flush bug.
- `/metrics` exposes all three defaults with identical metric names and
  label sets across languages.
- Hitting `/widgets/abc` and `/widgets/def` produces **one** route label
  series, not two.
- `scripts/parity.sh` gains a check diffing exported metric names and label
  keys between the two services.

## Flag back before finishing

- Any metric name or label that ADR 0003's scheme made awkward once real
  instrumentation libraries were involved — `prometheus-fastapi-
  instrumentator` and `client_golang` have opinions, and if matching them
  costs more than it's worth, say so.
- Whether the Python auto-instrumentation produces a span tree shaped the
  same as Go's. If the two differ structurally, that's worth knowing before
  anyone builds dashboards on it.
