# 0003 — Name metrics for Prometheus, put service identity in `target_info`

**Status:** accepted (2026-08-14)
**Date:** 2026-08-14
**Chunk:** [01 — Decisions and ADRs](../../tasks/01-decisions.md)

## Context

The spec (§ Metrics) asks for a naming convention "documented and consistent
between languages (propose one — e.g. `<service>_<noun>_<unit>_<suffix>`)", for
three default metrics on every route with no per-handler code, for a standard
label set, and for a cardinality guardrail "enforced by the default
instrumentation". Chunk 08's "flag back" section says in advance that
`prometheus-fastapi-instrumentator` and `client_golang` "have opinions, and if
matching them costs more than it's worth, say so." So the load-bearing question
is not what the names *should* be in the abstract — it is whether both libraries
can emit the same bytes.

**Current Prometheus guidance** (prometheus.io/docs/practices/naming, read
2026-08-14) — verbatim: metrics "SHOULD use base units (e.g. seconds, bytes,
meters - not milliseconds, megabytes, kilometers)"; "SHOULD have a suffix
describing the unit, in plural form"; "an accumulating count has `total` as a
suffix, in addition to the unit if applicable"; "SHOULD have a (single-word)
application prefix relevant to the domain the metric belongs to. The prefix is
sometimes referred to as `namespace` by client libraries"; "Do not put the label
names in the metric name"; "Do not use labels to store dimensions with high
cardinality (many different label values), such as user IDs, email addresses, or
other unbounded sets of values." The page also notes that OpenTelemetry "do[es]
not recommend or even do not allow including information about a metric unit and
type in the metric name", while Prometheus "strongly recommends" it — so the two
conventions actively disagree and a choice is required.

**Current OTel HTTP semconv** (semconv 1.44.0): `http.server.request.duration`
is a stable Histogram in seconds with advisory bucket boundaries
`[0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 2.5, 5, 7.5, 10]`;
`http.server.active_requests` is an UpDownCounter, unit `{request}`, still
Development/Opt-In. Required attributes `http.request.method` and `url.scheme`;
conditionally required `http.response.status_code`, `http.route`, `error.type`.
`http.request.method` MUST be set to `_OTHER` for methods not known to the
instrumentation.

**What the libraries actually emit.** Both spiked
(`scratchpad/adr-0002-0003/`, client_golang v1.24.1, prometheus-client 0.26.0),
declaring the same three metrics by hand with labels `method`/`route`/`status`.
Go:

```
# TYPE http_server_request_duration_seconds histogram
http_server_request_duration_seconds_bucket{method="GET",route="/widgets/{id}",status="200",le="0.005"} 0
...
http_server_request_duration_seconds_bucket{method="GET",route="/widgets/{id}",status="200",le="1"} 1
http_server_request_duration_seconds_sum{...} 0.03
http_server_request_duration_seconds_count{...} 1
# TYPE http_server_requests_total counter
http_server_requests_total{method="GET",route="/widgets/{id}",status="200"} 1
```

Python, same declarations:

```
# TYPE http_server_requests_total counter
http_server_requests_total{method="GET",route="/widgets/{id}",status="200"} 1.0
# HELP http_server_requests_created help
# TYPE http_server_requests_created gauge
http_server_requests_created{method="GET",route="/widgets/{id}",status="200"} 1.786754597680987e+09
...
http_server_request_duration_seconds_bucket{le="1.0",method="GET",route="/widgets/{id}",status="200"} 1.0
```

**The names and label sets match exactly. Five other things do not**, and every
one of them would fail a naive text diff in `scripts/parity.sh`:

1. Python emits a `_created` gauge alongside every counter and histogram; Go
   emits none.
2. Bucket boundaries render as `le="1"` in Go and `le="1.0"` in Python.
3. Go orders families alphabetically and puts `le` last; Python preserves
   registration order and sorts label keys alphabetically.
4. Default histogram buckets differ: Go's `DefBuckets` is
   `[0.005 0.01 0.025 0.05 0.1 0.25 0.5 1 2.5 5 10]`; Python's `DEFAULT_BUCKETS`
   is `(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0, inf)`.
   Python's happens to equal the OTel advisory set exactly; Go's does not.
5. The default registries are wildly asymmetric. Go's `promhttp.Handler()`
   exposes 38 families (`go_*`, `process_*`, `promhttp_metric_handler_*`);
   Python's exposes 4 on macOS (`python_gc_collections`,
   `python_gc_objects_collected`, `python_gc_objects_uncollectable`,
   `python_info`) — and `process_*` only appears on Linux, where
   `prometheus_client`'s `ProcessCollector` can read `/proc`.

**`client_golang`'s `promhttp` helpers cannot produce our label set.** Also
spiked, and the failure is loud:

```
--- promhttp magic-label panic check ---
PANIC: metric partitioned with non-supported labels
--- promhttp with only code+method, method case ---
ok_total{code="201",method="get"} 1
ok_total{code="201",method="unknown"} 1
```

`InstrumentHandlerCounter`/`Duration`/`InFlight` accept "zero, one, or two
non-const non-curried labels" and "the only allowed label names are `code` and
`method`. The function panics otherwise." A `route` label must be pre-curried
per route via `MustCurryWith`. They also lower-case the method (`method="get"`)
and map unrecognized methods to `unknown` — the second `Inc` above was a
`PROPFIND`. `prometheus-fastapi-instrumentator` has the mirror-image opinions:
its defaults are `http_requests_total{handler,status,method}` and
`http_request_duration_seconds{handler,method}`, with status codes "grouped into
`2xx`, `3xx` and so on", unmatched requests grouped into `handler="none"`, and
label *names* hardcoded per built-in metric. The two libraries' out-of-the-box
outputs are not reconcilable with each other at all — different metric names,
different label names, different label *values* for the same request.

## Decision

### 1. The three defaults, exactly

| what | name | type | labels |
| --- | --- | --- | --- |
| request count | `http_server_requests_total` | counter | `method`, `route`, `status` |
| request duration | `http_server_request_duration_seconds` | histogram | `method`, `route`, `status` |
| in-flight requests | `http_server_active_requests` | gauge | `method`, `route` |

Base units (seconds), `_total` on the counter, `_seconds` on the histogram, no
units in label names — per the Prometheus guidance quoted above. The
`http_server_` prefix rather than bare `http_` reserves `http_client_*` for the
outbound calls Phase 2 will bring, matching the split OTel semconv already
draws. `http_server_request_duration_seconds` and `http_server_active_requests`
are *also* exactly what OTel semconv renders into Prometheus, so these names are
idiomatic under both conventions at once.

`http_server_active_requests` carries no `status` label — the status of an
in-flight request is not yet known. This is a deliberate asymmetry with the
other two and both languages must reproduce it.

The counter is shipped explicitly even though `http_server_request_duration_seconds_count`
carries the same information with the same labels. It costs one extra series per
label combination against fifteen histogram bucket series, the spec asks for
three defaults by name, `http_..._requests_total` is the name every existing
dashboard and alert reaches for, and both libraries' own defaults ship a
separate counter too.

### 2. Label values are drawn from closed sets

| label | value | source |
| --- | --- | --- |
| `method` | upper-case HTTP method (`GET`, `POST`, …); `_OTHER` for anything not in RFC 9110 + `PATCH` + `QUERY` | the request, filtered through a fixed allowlist |
| `route` | the registered path template, e.g. `/widgets/{id}`; `__unmatched__` when no route matched | the operation registry — never `r.URL.Path` / `request.url.path` |
| `status` | the numeric status code as a decimal string, e.g. `404` | the response |

Upper-case methods and `_OTHER` follow OTel semconv, so metric label values and
span attribute values agree even though their *keys* don't (see below).
Deliberately **not** `client_golang`'s lower-case `get`/`unknown`, and
deliberately **not** the FastAPI instrumentator's `2xx` grouping — a status
label that can't distinguish 401 from 404 from 429 has given up the reason it
exists, and the full code is bounded at well under 100 values in practice.

`__unmatched__` matters more than it looks: instrumentation that labels 404s
with the concrete path turns any port scanner into an unbounded-cardinality
incident. That is the single most common way this goes wrong in production, so
the sentinel is part of the decision, not an implementation detail.

**Metric labels use Prometheus spellings; span attributes use OTel spellings.**
Two surfaces, two governing standards, one documented translation:

| fact | metric label (Prometheus exposition) | span attribute (OTLP) |
| --- | --- | --- |
| method | `method` | `http.request.method` |
| route | `route` | `http.route` |
| status | `status` | `http.response.status_code` |

The rule generating that table: *where a spelling is idiomatic under both
conventions, use it (which is why the metric names above are OTel's); where they
conflict, Prometheus wins on the Prometheus wire and OTel wins on the OTLP wire.*
Prometheus's own guidance and every community dashboard use short label names,
and `sum by (route)` reads better than `sum by (http_route)` a hundred times a
day.

### 3. The default metrics are **not** prefixed with the service name

`http_server_requests_total`, not `widget_svc_http_server_requests_total`. The
Prometheus "application prefix" rule is about avoiding collisions between
different *things*; these are the same thing in every service, distinguished by
the target's `job`/`instance` labels. Prefixing them makes every cross-service
dashboard and every "top 5 slowest endpoints in the fleet" query impossible
without `{__name__=~"..."}` gymnastics, and it would make chunk 08's parity check
("diff exported metric names between the two services") compare two different
strings by construction.

**Custom metrics are prefixed.** Pattern:

```
<namespace>_<subsystem>_<noun>[_<unit>]_<suffix>
```

- `namespace` — from config key `observability.metrics.namespace`
  (`MINT_OBSERVABILITY__METRICS__NAMESPACE`, per
  [0002](0002-environment-variable-naming.md)), defaulting to `service_name`
  with `-` → `_`. The copier validator `^[a-z][a-z0-9-]{1,38}[a-z0-9]$`
  guarantees the result is always a legal Prometheus name prefix, so the
  namespace can never be invalid — a mechanical guarantee, not a review item.
- `subsystem` — the domain the metric belongs to (`widgets`, `repository`).
- `unit` — base unit, plural, omitted for counts of things.
- `suffix` — `_total` for counters.

| example | type |
| --- | --- |
| `widget_svc_widgets_created_total` | counter |
| `widget_svc_repository_query_duration_seconds` | histogram |
| `widget_svc_cache_size_bytes` | gauge |
| `widget_svc_queue_depth` | gauge (unitless count) |

Both libraries have first-class `namespace`/`subsystem` support, so this is
free in each. This does mildly bend Prometheus's "single-word" prefix advice —
`widget_svc` is two tokens — but the alternative is an eighth copier question
asking for a one-word namespace, and the reason for the rule (collision
avoidance, domain grouping) is fully served.

### 4. `service_owner` is **not** a label. Identity goes in `target_info`

```
# HELP target_info Information about this service instance.
# TYPE target_info gauge
target_info{service_name="widget-svc",service_version="1.4.2",service_owner="payments-platform",deployment_environment_name="prod"} 1
```

One series per target, value always 1. Neither is `service`, `service_version`
or `env` a label on the other metrics.

`service_owner` is bounded, so cardinality is genuinely not the objection. Three
other things are. First, a label that never varies within a service is not a
dimension — it is metadata, and putting it on every series adds bytes to every
sample and every scrape while enabling no aggregation that `job` doesn't already
enable. Second, and decisively: **a re-org would break every time series in the
service.** Changing `service_owner` from `payments-platform` to `payments-core`
changes the identity of every series, so `rate()` returns nothing across the
boundary, every recording rule resets, and every historical query has to `or`
two owner values together forever. Under `target_info` a re-org creates exactly
one new series. Third, ownership genuinely belongs to a service catalogue, not a
process — the process is the one component that has no independent knowledge of
who owns it.

Nothing is lost at query time. Prometheus 3.x's `info()` function defaults to
`target_info` and joins on `job`/`instance`:

```promql
info(rate(http_server_request_duration_seconds_count[5m]), {service_owner=~".+"})
```

and pre-3.x, or in any other PromQL engine:

```promql
sum by (service_owner) (
  rate(http_server_requests_total[5m])
  * on (job, instance) group_left(service_owner) target_info
)
```

The name `target_info` and the `service_name` / `service_version` /
`deployment_environment_name` label spellings are exactly what the OTel
Prometheus exporter produces from resource attributes, so a Phase 2/3 move to
OTel metrics keeps the same series and the same queries. `service_owner` is a
Mint extension; semconv has no owner attribute. Spiked: `prometheus_client`'s
`Info("target", …)` and a plain `Gauge("target_info", …)` produce byte-identical
output, and Go has no `Info` type — so **both languages use a plain gauge**, and
the two exposition lines match exactly.

If this gets overridden and `service_owner` must be a real label, it belongs in
`relabel_configs`/a `ServiceMonitor` in Phase 3, not in application code — the
platform, not the service, is where the fleet-wide re-org gets applied once.

### 5. The cardinality rule, stated so it can be enforced

> **Every label value on a Mint metric must come from a set that is enumerable
> when the process starts.** If a value's set is not enumerable at startup, the
> label does not exist.

Concretely:

1. **`route` comes from the operation registry**, never from the request URL.
   Requests matching no route get `__unmatched__`.
2. **`method` comes from a fixed allowlist**, anything else becomes `_OTHER`.
3. **`status` is the numeric code**, always within `[100, 599]`.
4. **The three defaults carry no other labels.** Not `user_id`, not
   `tenant`, not `error_message`, not `client_ip`, not `user_agent`.
5. **For custom metrics, these value sources are banned outright**: URL paths
   and path parameters, query strings, request or response headers, request or
   response bodies, user/tenant/account/session IDs, e-mail addresses, IP
   addresses, client hostnames, timestamps, error messages, free-form text,
   UUIDs, and anything derived from them.
6. **Series budget.** The three defaults are bounded by
   `|routes| × |methods in use| × |status codes in use|`, plus one
   `__unmatched__` group. A test asserts an explicit upper bound so a
   cardinality regression fails CI rather than a Prometheus.

Enforcement is structural, not documentary:

- All metric construction lives in `internal/observability`. `make lint` fails
  on a `prometheus.New*` / `Counter(` / `Histogram(` / `Gauge(` outside it, the
  same grep-shaped rule as "nothing outside `internal/config` reads an env var".
  Handlers cannot mislabel a metric because handlers cannot reach one.
- Chunk 08 already requires the test that `/widgets/abc` and `/widgets/def`
  produce one series. Add two siblings: an unrouted path produces
  `route="__unmatched__"`, and a `PROPFIND` produces `method="_OTHER"`.
- The rule is restated in `AGENTS.md` (rendered from `docs/agents.md`) as a
  "don't do this" boundary, which the spec already asks for.

### 6. Histogram buckets are declared explicitly, in both languages

`[0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 2.5, 5, 7.5, 10]` —
the OTel semconv advisory set for `http.server.request.duration`. Python's
`DEFAULT_BUCKETS` already equals this; Go's `DefBuckets` omits 0.075, 0.75 and
7.5. Both templates state the list literally anyway, so an upstream default
change can't silently desynchronize the two services.

### 7. `scripts/parity.sh` compares parsed metrics, not text

Given the five exposition differences above, the metric parity check must parse
`/metrics` and compare, for Mint-owned families only, the set of
`(family name, sorted label key set, type)`. Mint-owned = the three defaults,
`target_info`, and `^<namespace>_`. Runtime collectors (`go_*`, `process_*`,
`promhttp_*`, `python_*`) stay enabled in both — they are useful — and are
excluded from the diff by that allowlist. `_created` series are suppressed
(see below) rather than filtered, because leaving them creates real series in
real Prometheus servers that only one of the two languages has.

## Alternatives considered

**Full OTel semconv label names — `http_request_method`, `http_route`,
`http_response_status_code`.** Genuinely tempting: it would make metric labels,
span attributes and any future OTel-SDK-emitted metrics all agree, with zero
translation table. Lost on ergonomics against the standard Mint actually
exposes. The `/metrics` endpoint speaks the Prometheus exposition format, whose
own naming guide and whose entire dashboard ecosystem use short label names;
`sum by (http_route)` is a tax paid on every query for a consistency that only
pays off in a Phase 2/3 migration that may not happen. Note the asymmetry in
which we did adopt semconv: metric *names* and label *values* are semconv's,
because there they cost nothing.

**Prefix everything with the service namespace** (`widget_svc_http_requests_total`),
the most literal reading of the spec's `<service>_<noun>_<unit>_<suffix>` sketch
and of Prometheus's "application prefix" rule. Rejected: it makes fleet-wide
queries and shared dashboards require metric-name regex matching, it duplicates
information the `job` label already carries, and it directly breaks chunk 08's
cross-language metric-name parity check. The rule's actual purpose — don't let
two different things collide on one name — doesn't apply to a metric that means
the same thing everywhere.

**Ship only the histogram and let `_count` be the request count.** Correct, and
saves one series per label set. Rejected because the spec names three defaults,
because `http_server_requests_total` is what alert rules and dashboards reach
for by reflex, and because the saving is ~6% of the series the histogram already
creates.

**Use the libraries' built-in HTTP instrumentation as-is** —
`promhttp.InstrumentHandler*` and `Instrumentator().instrument()`. This is the
path of least code, and it is the thing chunk 08 explicitly asked us to
evaluate. It cannot work: the spike shows `promhttp` *panics* with a `route`
label present, lower-cases methods, and emits `unknown` for unrecognized ones;
the FastAPI instrumentator hardcodes `handler`/`status` as label names, groups
status into `2xx`, and uses `none` for unmatched routes. Adopting either one's
defaults means adopting names and values the other cannot produce. Both
libraries' *primitives* (`CounterVec`, `HistogramVec`, `GaugeVec`) produce our
exact target output, as the spikes demonstrate — so the decision is to write one
small middleware per language against the primitives and take neither library's
HTTP opinions. That is roughly 60 lines each and it is the honest answer to
chunk 08's "if matching them costs more than it's worth, say so": matching them
to each other is impossible, so matching *neither* is the cheap option.

**Milliseconds for duration.** Rejected outright — Prometheus says base units,
`_seconds` is universal, and Grafana formats seconds natively.

**Summaries instead of histograms.** Quantiles can't be aggregated across
instances, which makes a fleet-level p99 impossible. Histograms it is. Native
histograms are the interesting future option but are still stabilizing and would
need matching support on both clients and in the storage backend; revisit when
there are real services and a real Prometheus to point at.

**Put `service`/`env`/`service_version` on every series as const labels.**
Common in the wild, and it makes local `/metrics` self-describing without a
scrape config. Rejected for the same reasons as `service_owner`, plus a concrete
one: a `service` label colliding with a target label set by `honor_labels` or a
`ServiceMonitor` produces `exported_service`, which silently breaks the exact
dashboards it was added to serve.

## Consequences

**Easy.** One PromQL vocabulary across the fleet regardless of language.
`rate(http_server_requests_total{route="/widgets/{id}",status=~"5.."}[5m])`
works identically against a Go and a Python service. Metric names are legal and
idiomatic under both Prometheus and OTel conventions, so a later move to OTel
metrics is a re-plumbing, not a dashboard rewrite. Ownership, version and
environment are queryable via one `info()` call and survive a re-org. The
cardinality rule is short enough to fit in `AGENTS.md` and mechanical enough to
test.

**Hard.** Neither language gets to use its library's turnkey HTTP
instrumentation — that is ~60 lines of middleware per language that has to be
maintained and parity-checked, and it is the price of the two languages agreeing
at all. The `http_server_active_requests` metric lacks a `status` label while
the other two have one; that irregularity is correct but will look like a bug to
someone reading the code, so it needs a comment at the declaration site.

**Concrete work items this creates for chunk 08:**

| finding | required action |
| --- | --- |
| Python emits `_created` for every counter and histogram; Go emits none | call `prometheus_client.disable_created_metrics()` in `internal/observability`. Note the alternative, `PROMETHEUS_DISABLE_CREATED_SERIES=true`, is an env var read outside `internal/config` and is therefore forbidden by [0002](0002-environment-variable-naming.md) decision 8 and the `make lint` rule. |
| `le="1"` (Go) vs `le="1.0"` (Python); different family and label ordering | parity compares parsed `(family, sorted label keys, type)`, never raw text |
| Go `DefBuckets` ≠ Python `DEFAULT_BUCKETS` ≠ OTel advisory | declare the bucket list literally in both templates |
| default registries expose 38 vs 4 families, and Python's `process_*` is Linux-only | parity restricted to a Mint-owned family allowlist |
| `promhttp` panics on a `route` label, lower-cases methods, emits `unknown` | hand-written middleware in Go; uppercase methods, `_OTHER` sentinel |
| instrumentator hardcodes `handler`/`status`, groups to `2xx`, uses `none` | hand-written middleware in Python; same names and sentinels as Go |

**One asymmetry left open, and it is a real one.** `prometheus_client` in a
multi-process deployment (gunicorn/uvicorn with `--workers N`) needs
`PROMETHEUS_MULTIPROC_DIR` and a `MultiProcessCollector`, and gauges need an
explicit `multiprocess_mode` — `livesum` for `http_server_active_requests` — or
`/metrics` reports one worker's view. Go has no equivalent problem. Phase 1
assumes a **single worker process** in Python; `docs/architecture.md` must say
so, and the day someone scales workers, that in-flight gauge is the first thing
that lies. This is the one place the two languages cannot be made to behave
identically without infrastructure Phase 1 doesn't have.

**To reverse it.** Renaming a metric or a label after services are deployed
breaks every dashboard, alert and recording rule that references it, and
Prometheus offers no rename migration — the standard remedy is to emit both
names for one retention window and then drop the old one, which means a
deliberate template version, a `_migrations` entry, and a fleet-wide deploy.
Adding a label to an existing metric is equally breaking, because it changes
series identity and resets every `rate()` across the boundary. Adding a *new*
metric is free. Practically: this decision is cheap to change today, expensive
after the first service ships, and irreversible-in-practice after the first
dashboard is built on it.
