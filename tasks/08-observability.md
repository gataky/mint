# 08 — Tracing and metrics

**Spec:** § Tracing, § Metrics
**Depends on:** 07. **ADR 0003 is binding here** — it fixes the names, the
labels and the cardinality rule, and it establishes that **neither language's
turnkey HTTP instrumentation is usable**. ADR 0002 § 8 fixes how the OTLP
endpoint and the service identity resolve.
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

2. **Quiet local default.** When `MINT_ENV=local` and no OTLP endpoint is
   configured, install a **no-op exporter** (stdout behind an explicit
   flag). A fresh `make run` must not emit a single connection-refused
   retry.

   **Never construct an exporter without an explicit endpoint.** The OTLP
   gRPC exporter defaults to `http://localhost:4317`, so an exporter built
   with no endpoint produces exactly the retry storm this criterion forbids.
   ADR 0002 names this as the quiet-local-`make run` bug specifically.

3. **The endpoint resolves through `internal/config`, not through the SDK.**
   Chunk 03 built the chain; use it and do not read an OTel env var here —
   `make lint`'s env-var rule forbids it, and `--print-config` has to be able
   to show the endpoint actually in use:

   ```
   MINT_OBSERVABILITY__TRACING__OTLP_ENDPOINT
     → OTEL_EXPORTER_OTLP_TRACES_ENDPOINT
       → OTEL_EXPORTER_OTLP_ENDPOINT
         → YAML
           → unset ⇒ no-op exporter
   ```

   Protocol, headers, timeout, compression and sampler are **not** modelled
   by Mint and are left entirely to the SDK's own env vars. `localhost:4317`
   stays the conventional local value someone types, not a default the code
   supplies.

4. **Mint owns service identity; OTel does not.** Build the `Resource`
   explicitly from Mint config and **merge it last so it wins over
   `OTEL_RESOURCE_ATTRIBUTES`**. `OTEL_SERVICE_NAME` and
   `OTEL_RESOURCE_ATTRIBUTES` are ignored for `service.name`,
   `service.version` and `deployment.environment.name`. If they weren't, the
   `service`/`env` fields on a log line could disagree with the same fields
   on a span, and someone tracing a reported error from a log lands nowhere.

5. **Auto-instrument the transport.** Every inbound request starts or joins
   a span, with zero per-handler boilerplate. Span names use the route
   template, never the concrete path. Python uses real OTel ASGI
   instrumentation (`opentelemetry-instrumentation-fastapi`, pinned `0.65b0`)
   in place of the manual span ADR 0010's spike used.

6. **Propagate through service and repository layers** — `context.Context`
   in Go, the equivalent in Python. A repository call must appear as a child
   span of its request.

7. **Flush on shutdown.** Wire the provider flush into the drain sequence
   chunk 06 built. Spans from final requests are silently lost otherwise —
   this is the single most common OTel bug, and the verify script must
   assert against it.

8. **Log correlation closes the loop.** Chunk 04 built the logger to read
   `trace_id`/`span_id` from the active span context, so with a real provider
   installed they should now appear **with no logging changes at all**. ADR
   0010 says so explicitly; verify it. If the logger needs a change here,
   chunk 04's integration was wrong and that is the finding, not a patch.

9. **Span attributes use OTel spellings; metric labels use Prometheus
   spellings.** Two surfaces, two governing standards, one documented
   translation:

   | fact | metric label | span attribute |
   | --- | --- | --- |
   | method | `method` | `http.request.method` |
   | route | `route` | `http.route` |
   | status | `status` | `http.response.status_code` |

   Label *values* are the same on both sides (upper-case methods, `_OTHER`
   sentinel), so only the keys differ.

### Metrics

10. **`/metrics` on the admin port**, Prometheus format.

11. **Write the middleware by hand, in both languages, against the client
    libraries' primitives.** This is the chunk's biggest change from the
    spec's assumption, and both halves were measured:

    - `promhttp.InstrumentHandlerCounter`/`Duration`/`InFlight` accept only
      `code` and `method` as non-const labels and **panic** otherwise:
      `PANIC: metric partitioned with non-supported labels`. They also
      lower-case the method (`method="get"`) and map unrecognized methods to
      `unknown`.
    - `prometheus-fastapi-instrumentator` hardcodes `handler`/`status` as
      label names, groups status codes into `2xx`/`3xx`, and uses
      `handler="none"` for unmatched requests.

    The two libraries' out-of-the-box outputs are not reconcilable with each
    other at all — different metric names, different label names, different
    label *values* for the same request. Their **primitives** (`CounterVec`,
    `HistogramVec`, `GaugeVec`) produce the exact target output. So: roughly
    60 lines of middleware per language, taking neither library's HTTP
    opinions. Matching them to each other is impossible; matching *neither*
    is the cheap option.

12. **The three defaults, exactly:**

    | what | name | type | labels |
    | --- | --- | --- | --- |
    | request count | `http_server_requests_total` | counter | `method`, `route`, `status` |
    | request duration | `http_server_request_duration_seconds` | histogram | `method`, `route`, `status` |
    | in-flight requests | `http_server_active_requests` | gauge | `method`, `route` |

    Not prefixed with the service name — these mean the same thing in every
    service and are distinguished by the target's `job`/`instance` labels;
    prefixing them makes every fleet-wide dashboard query impossible and
    breaks the cross-language name parity check by construction.

    **`http_server_active_requests` carries no `status` label** — the status
    of an in-flight request is not yet known. This asymmetry is deliberate,
    both languages must reproduce it, and it needs a comment at the
    declaration site because it will look like a bug.

13. **Label values come from closed sets:**

    | label | value |
    | --- | --- |
    | `method` | upper-case HTTP method; **`_OTHER`** for anything outside a fixed allowlist (RFC 9110 + `PATCH` + `QUERY`) |
    | `route` | the registered path template from the operation registry, never `r.URL.Path` / `request.url.path`; **`__unmatched__`** when no route matched |
    | `status` | the numeric code as a decimal string, e.g. `404` — never grouped into `2xx` |

    `__unmatched__` matters more than it looks: labelling 404s with the
    concrete path turns any port scanner into an unbounded-cardinality
    incident. It is part of the decision, not an implementation detail.

14. **Histogram buckets are declared literally in both templates:**
    `[0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 2.5, 5, 7.5, 10]`
    — the OTel semconv advisory set. Python's `DEFAULT_BUCKETS` already
    equals it; Go's `DefBuckets` omits 0.075, 0.75 and 7.5. State the list
    anyway in both, so an upstream default change can't silently desynchronize
    the two services.

15. **`service_owner` is not a label. Identity goes in `target_info`:**

    ```
    # TYPE target_info gauge
    target_info{service_name="widget-svc",service_version="1.4.2",service_owner="payments-platform",deployment_environment_name="prod"} 1
    ```

    One series per target, value always 1. Neither `service`, `service_version`
    nor `env` is a label on the other metrics. The decisive reason is not
    cardinality: **a re-org would change the identity of every time series in
    the service**, so `rate()` returns nothing across the boundary and every
    recording rule resets. Under `target_info` a re-org creates one new
    series.

    Use a **plain gauge in both languages** — Go has no `Info` type, and
    `prometheus_client`'s `Info("target", …)` and a plain gauge produce
    byte-identical output. The label spellings are exactly what the OTel
    Prometheus exporter produces, so a later move to OTel metrics keeps the
    same series and the same queries.

16. **Call `prometheus_client.disable_created_metrics()`** in Python's
    `internal/observability`. Python emits a `_created` gauge alongside every
    counter and histogram and Go emits none, and those are real series in a
    real Prometheus that only one language has. Suppress them rather than
    filter them. The alternative — `PROMETHEUS_DISABLE_CREATED_SERIES=true` —
    is an env var read outside `internal/config` and is forbidden by ADR 0002
    § 8 and the `make lint` rule.

17. **Custom metric naming**, for the metrics a real service will add later:

    ```
    <namespace>_<subsystem>_<noun>[_<unit>]_<suffix>
    ```

    `namespace` comes from config key `observability.metrics.namespace`
    (`MINT_OBSERVABILITY__METRICS__NAMESPACE`), defaulting to `service_name`
    with `-` → `_`. Examples: `widget_svc_widgets_created_total`,
    `widget_svc_repository_query_duration_seconds`,
    `widget_svc_cache_size_bytes`. Both libraries have first-class
    `namespace`/`subsystem` support, so this is free in each.

18. **The cardinality rule, enforced structurally rather than documented:**

    > Every label value on a Mint metric must come from a set that is
    > enumerable when the process starts. If a value's set is not enumerable
    > at startup, the label does not exist.

    - **All metric construction lives in `internal/observability`.** `make
      lint` fails on a `prometheus.New*` / `Counter(` / `Histogram(` /
      `Gauge(` outside it — the same grep-shaped rule as the env var check.
      Handlers cannot mislabel a metric because handlers cannot reach one.
    - Banned value sources for custom metrics, stated as a list in
      AGENTS.md: URL paths and path parameters, query strings, headers,
      request/response bodies, user/tenant/account/session IDs, e-mail
      addresses, IP addresses, client hostnames, timestamps, error messages,
      free-form text, UUIDs, and anything derived from them.
    - **Series budget test**: the three defaults are bounded by
      `|routes| × |methods in use| × |status codes in use|` plus one
      `__unmatched__` group. Assert an explicit upper bound so a cardinality
      regression fails a test rather than a Prometheus.

19. **`docs/architecture.md`** — note where the observability wiring lives
    and why it's isolated, and record the metric-label / span-attribute
    translation table from item 9. Record the cardinality rule in AGENTS.md
    (rendered from `docs/agents.md`) as a "don't do this" boundary.

    Also record, because it is the one place the two languages genuinely
    cannot be made identical: **Phase 1 assumes a single Python worker
    process.** `prometheus_client` under `--workers N` needs
    `PROMETHEUS_MULTIPROC_DIR`, a `MultiProcessCollector`, and
    `multiprocess_mode="livesum"` on the in-flight gauge, or `/metrics`
    reports one worker's view. Go has no equivalent problem. The day someone
    scales workers, `http_server_active_requests` is the first thing that
    lies.

## Out of scope

Alerting, dashboards, exemplars, custom business metrics beyond the three
defaults, OTel Collector configuration, log shipping, multi-process metric
aggregation.

## Deliverables

- Real tracing and metrics filling the chain positions from chunk 06
- `internal/observability` in both templates, with tests
- Hand-written metrics middleware in both, ~60 lines each
- `/metrics` on the admin port in both
- Metric-construction lint rule wired into `make lint`

## Acceptance criteria

- `make run` with no Jaeger running and no endpoint configured produces
  **zero** exporter errors or retries in either language.
- With an endpoint configured, a request produces a trace with a transport
  span and a child repository span, in both languages, with matching span
  names and attribute keys.
- `OTEL_SERVICE_NAME=something-else` does not change `service.name` on an
  exported span or on a log line.
- Log lines emitted during a traced request carry `trace_id` and `span_id`
  matching the span — and still omit them entirely outside a trace — **with
  no change to `internal/logging`**.
- SIGTERM during an in-flight request results in that request's span being
  exported. Assert this in `scripts/verify-template.sh`; it's the flush bug.
- `/metrics` exposes all three defaults with the exact names, types and
  label sets in the table above, in both languages.
- Hitting `/widgets/abc` and `/widgets/def` produces **one** route label
  series, not two.
- An unrouted path produces `route="__unmatched__"`; a `PROPFIND` produces
  `method="_OTHER"`. Both tested, both languages.
- `service_owner` appears on `target_info` and on **no other series**;
  `target_info` carries the same label **keys** in both languages. Its
  exposition text is not compared (ADR 0017 — and ADR 0003 already required
  parsed comparison over raw text).
- Python's `/metrics` contains no `_created` series.
- The declared bucket boundaries are identical between the two services.
- The series-budget test fails when a label is added to one of the three
  defaults. Demonstrate, then revert.
- `make lint` fails when a metric is constructed outside
  `internal/observability`. Demonstrate, then revert.
- `scripts/parity.sh` gains a metrics check that **parses** both `/metrics`
  outputs and compares `(family name, sorted label key set, type)` over a
  Mint-owned allowlist — the three defaults, `target_info`, and
  `^<namespace>_`. **Never a raw text diff.** Go and Python differ in
  `le="1"` vs `le="1.0"`, in family and label ordering, and in default
  registry contents (38 families vs 4, with `process_*` Linux-only in
  Python); runtime collectors stay enabled in both and are excluded by the
  allowlist.

## Flag back before finishing

- Whether the Python auto-instrumentation produces a span tree shaped the
  same as Go's. If the two differ structurally, that's worth knowing before
  anyone builds dashboards on it.
- Whether 60 lines was the real cost of the hand-written middleware. ADR
  0003 accepted the maintenance burden on that estimate; materially more is
  worth reporting.
- Anything that made the Mint-owned allowlist hard to define — if a runtime
  collector emits a family that collides with the allowlist pattern, the
  parity check silently widens, and that should be caught now.

*Settled, do not re-open:* the three metric names, the label sets,
`service_owner` living in `target_info`, the explicit bucket list, and the
decision to hand-write the middleware rather than use `promhttp` or
`prometheus-fastapi-instrumentator`. ADR 0003, approved — the "if matching
them costs more than it's worth, say so" question this chunk used to ask has
been answered: matching them to each other is impossible.
