# widget-svc (Go)

A small HTTP service: three layers, structured logging, metrics, tracing,
RFC 9457 errors, and an OpenAPI 3.1 document served with Swagger UI.

This is one of two reference implementations in [Mint](../../README.md). The Python
service exposes the same API and the same Makefile targets; a client should not
be able to tell which one it is talking to.

## Quick start

```sh
direnv allow      # picks up the pinned Go from .tool-versions
make run
```

Then:

```sh
curl localhost:8080/widgets
curl localhost:9080/healthz
open  http://localhost:8080/docs
```

## Commands

| target | what it does |
| --- | --- |
| `make run` | boots the service |
| `make build` | builds `bin/widget-svc` |
| `make test` | unit tests with a coverage summary |
| `make test-integration` | tests behind the `integration` build tag |
| `make lint` | `go vet`, golangci-lint, and the config-discipline check |
| `make fmt` | gofumpt, in place |
| `make config` | the effective config and where each value came from |
| `make clean` | removes `bin/` |
| `make help` | this list, generated from the Makefile |

Linters and formatters are pinned in `go.mod` as `tool` directives and run via
`go tool`. There is nothing to install globally.

## Layout

**One file per resource, in every layer.** Adding a resource means adding four
files and one line in the composition root — never inventing a convention.

```
cmd/widget-svc/main.go            composition root — wires everything, owns signals

internal/domain/                  entities and the error taxonomy
  widget.go  order.go             (imports nothing else in the service)
internal/service/                 business rules; declares the repository interfaces
  widget.go  order.go
internal/repository/memory/       repository implementations
  widget.go  order.go
internal/transport/http/          handlers, middleware, error mapping, listeners
  widget.go  order.go

internal/config/                  the ONLY place that reads env vars or files
internal/logging/                 the two log tiers
internal/observability/           metrics registry and tracer provider
config/config.yaml                checked-in defaults
```

`internal/transport/http/` nests deliberately. There is one transport today; the
nesting is what makes a second one an addition rather than a refactor.

### The layer rule

Dependencies point inward. `domain` imports nothing from the service; everything
imports `domain`.

- **Transport** parses a request, validates its *shape*, calls the service, and
  serializes the result. No business logic.
- **Service** holds all business rules. It takes and returns domain types — no
  `http.Request`, no huma types, no driver types.
- **Repository** holds all persistence, behind an interface.

**The repository interface is declared in `internal/service`, not in
`internal/repository`.** The consumer owns the interface in Go: the service says
what it needs, and an implementation satisfies it without either importing the
other. `internal/repository/memory` is the only implementation today; a Postgres
one would be a sibling package chosen by `main.go`, and nothing else would
change.

### One resource depending on another

`orders` references `widgets`, which is the case a template has to show. The
order service declares a `WidgetLookup` interface with the single method it
needs, and `*service.Widgets` satisfies it without knowing orders exist. Copy
that rather than depending on the whole neighbouring service.

## API

| method | path | status | notes |
| --- | --- | --- | --- |
| GET | `/widgets` | 200 | every widget, oldest first |
| GET | `/widgets/{id}` | 200, 404 | |
| POST | `/widgets` | 201, 409, 422 | 409 on a duplicate name |
| GET | `/orders` | 200 | every order, oldest first |
| GET | `/orders/{id}` | 200, 404 | |
| POST | `/orders` | 201, 400, 422 | 400 if the widget does not exist |
| GET | `/openapi.json` | 200 | OpenAPI 3.1, generated from the handlers |
| GET | `/docs` | 200 | Swagger UI |
| GET | `/healthz` | 200 | admin port; liveness, touches no dependency |
| GET | `/readyz` | 200, 503 | admin port; runs the registered checks |
| GET | `/metrics` | 200 | admin port; Prometheus exposition |

Errors are RFC 9457 `application/problem+json`:

```json
{
  "type": "about:blank",
  "title": "Not Found",
  "status": 404,
  "detail": "no widget with id \"abc\"",
  "instance": "/widgets/abc"
}
```

A shape violation returns **422**, which is what both huma and FastAPI do by
default. A business-rule violation returns **400** — including ordering a widget
that does not exist, which is a bad *reference* in a well-formed request to a
route that does exist, not a missing `/orders` resource. Every response carries an
`X-Request-Id` header, echoing the inbound one if there was one.

## Configuration

Precedence, lowest to highest:

```
defaults in code  <  config/config.yaml  <  config/config.local.yaml  <  environment
```

Environment variables are `MINT_` + the config path upper-cased, with `__`
between levels and the key's own underscores preserved:

```
server.read_timeout  ->  MINT_SERVER__READ_TIMEOUT
logging.format       ->  MINT_LOGGING__FORMAT
```

`__` rather than `_` because single-underscore nesting cannot distinguish
`server.read_timeout` from `server.read.timeout`. A constant `MINT_` prefix
rather than the service name because Kubernetes injects `{SVCNAME}_PORT` into
every pod.

`make config` prints the effective values and names the source of each. An
invalid configuration fails at startup and reports **every** bad field at once.

## Ports

The API listens on `server.port` and health checks on `server.admin_port`. The
split buys drain visibility, not security — any client that can reach the pod IP
can reach every container port. Mid-drain a split admin port still answers
`/readyz` with `503 draining`; collapsed, it is connection-refused.

Setting `admin_port` equal to `port` collapses both onto one listener, and is
supported.

## Metrics

On the admin port at `/metrics`:

| metric | labels |
| --- | --- |
| `http_server_requests_total` | `method`, `route`, `status` |
| `http_server_request_duration_seconds` | `method`, `route`, `status` |
| `http_server_active_requests` | `method` |

Buckets are OpenTelemetry's advisory set, declared literally rather than taken
from the library's defaults.

`route` is the registered template, never the concrete path, and an unrouted
request is labelled `<unmatched>` — otherwise anyone could create unbounded
series by requesting random URLs.

The in-flight gauge carries no `route` label, because the route is not known
when a request begins. OpenTelemetry's own convention omits it for the same
reason.

**`service_owner` is not a label.** It lives on
`target_info{service_name,service_version,service_owner,deployment_environment_name}`,
joinable with Prometheus 3's `info()`. A re-org would otherwise change the
identity of every series and break `rate()` across the boundary.

The admin surface is not instrumented: a readiness probe every second and a
scrape every fifteen would be most of the metrics.

## Tracing

OpenTelemetry, wired only in `internal/observability`.

- **A real tracer provider is installed even with no collector configured.**
  The *exporter* becomes a no-op, not the tracer: spans are still created, so
  every log line still carries a `trace_id`, while a fresh `make run` emits no
  connection-refused retries.
- With `observability.tracing.otlp_endpoint` set, spans are exported over
  OTLP/HTTP.
- Span names are `{method} {route}` — the route template, matching the
  metrics label.
- W3C trace context is propagated, so an inbound `traceparent` continues the
  caller's trace rather than starting a new one.
- **The provider is flushed on shutdown**, after the drain. The spans for the
  last requests served are still queued and are silently lost otherwise.
- `/healthz`, `/readyz` and `/metrics` are not traced.

`trace_id` and `span_id` are added by a `slog.Handler` wrapper rather than at call sites, and are **omitted entirely when there
is no span** — never empty, never fabricated. An empty `trace_id` in an
aggregator is worse than an absent one: it looks like a trace that exists and
cannot be found.

**Mint owns identity and defers on transport.** `OTEL_SERVICE_NAME` and
`OTEL_RESOURCE_ATTRIBUTES` are deliberately ignored — logs and spans disagreeing
about `service` or `env` would break the error-to-trace path. The one ecosystem
variable honoured is `OTEL_EXPORTER_OTLP_ENDPOINT`, read as an explicitly
enumerated fallback inside `internal/observability` when `otlp_endpoint` is unset, so
`make config` still names its source.

## Not built yet

A generated `llms.txt`, and Copier templating. Authentication is deliberately
deferred to a gateway: the middleware chain has a named empty slot for it, and
the service warns at startup when `env != local` and none is registered.
