# widget-svc (Go)

A small HTTP service: three layers, structured logging, RFC 9457 errors, and an
OpenAPI 3.1 document served with Swagger UI.

This is one of two reference implementations in [Mint](../README.md). The Python
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

```
cmd/widget-svc/main.go          composition root — wires everything, owns signals
internal/config/                the ONLY place that reads env vars or files
internal/logging/               the two log tiers
internal/service/               business logic and the error taxonomy
internal/transport/http/        handlers, middleware, error mapping, listeners
config/config.yaml              checked-in defaults
```

`internal/transport/http/` nests deliberately. There is one transport today; the
nesting is what makes a second one an addition rather than a refactor.

### The layer rule

- **Transport** parses a request, validates its *shape*, calls the service, and
  serializes the result. No business logic.
- **Service** holds all business rules and the error taxonomy. It takes and
  returns plain Go types — no `http.Request`, no huma types, no driver types.

Widgets are held in memory. A real service would define a repository interface
in `internal/service`, implement it elsewhere, and inject it from `main.go`.

## API

| method | path | status | notes |
| --- | --- | --- | --- |
| GET | `/widgets` | 200 | every widget, oldest first |
| GET | `/widgets/{id}` | 200, 404 | |
| POST | `/widgets` | 201, 409, 422 | 409 on a duplicate name |
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
default. A business-rule violation returns **400**. Every response carries an
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

## Not built yet

OpenTelemetry tracing and a generated `llms.txt`. The seams are in place: `ctx`
is the first argument of every service method, the logger is reached through the
context, and the middleware chain has a named empty slot for tracing outside
metrics and logging.
