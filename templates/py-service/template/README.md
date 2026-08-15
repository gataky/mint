# {@ service_name @} (Python)

A small HTTP service: three layers, structured logging, metrics, tracing,
RFC 9457 errors, and an OpenAPI 3.1 document served with Swagger UI.

Minted from `{@ _copier_answers['_src_path'] @}`{% if _copier_answers['_commit'] %} at `{@ _copier_answers['_commit'] @}`{% endif %}.
`copier update` pulls later template changes in — see
[Updating from the template](#updating-from-the-template).

## Quick start

```sh
direnv allow      # picks up the pinned Python and uv from .tool-versions
uv sync
make run
```

Then:

```sh
{% if include_examples %}curl localhost:{@ port @}/widgets
{% endif %}curl localhost:{@ admin_port @}/healthz
open  http://localhost:{@ port @}/docs
```

## Commands

| target | what it does |
| --- | --- |
| `make run` | boots the service |
| `make build` | builds a wheel into `bin/` |
| `make test` | unit tests with a coverage summary |
| `make test-integration` | tests marked `integration` |
| `make lint` | ruff, ruff format --check, mypy --strict, and the config-discipline check |
| `make fmt` | ruff format and ruff --fix, in place |
| `make config` | the effective config and where each value came from |
| `make clean` | removes `bin/` and the tool caches |
| `make help` | this list, generated from the Makefile |

Linters and type checkers are pinned in `pyproject.toml`'s dev group and run via
`uv run`. There is nothing to install globally.

mypy is part of `lint` because Go type-checks as part of compilation and Python
does not. Without it, the two `lint` targets would not mean the same thing.

## Layout

**One module per resource, in every layer.** Adding a resource means adding four
modules and one line in the composition root — never inventing a convention.

```
src/{@ package_name @}/__main__.py        composition root — wires everything, owns signals

src/{@ package_name @}/domain/            entities and the error taxonomy
{% if include_examples %}  widget.py  order.py  errors.py  (imports nothing else in the service)
{% else %}  errors.py                       (imports nothing else in the service)
{% endif %}src/{@ package_name @}/service/           business rules; declares the repository Protocols
{% if include_examples %}  widgets.py  orders.py
{% endif %}src/{@ package_name @}/repository/memory/ repository implementations
{% if include_examples %}  widgets.py  orders.py
{% endif %}src/{@ package_name @}/api/               routers, middleware, problem+json, health
{% if include_examples %}  widgets.py  orders.py
{% endif %}
src/{@ package_name @}/config.py          the ONLY place that reads env vars or files
src/{@ package_name @}/log.py             the two log tiers
src/{@ package_name @}/observability.py   metrics registry and tracer provider
config/config.yaml                checked-in defaults
```

### The layer rule

Dependencies point inward. `domain/` imports nothing from the service;
everything imports `domain/`.

- **`api/`** parses a request, validates its *shape* (FastAPI does that from the
  type annotations), calls the service, and returns a model. No business logic.
- **`service/`** holds all business rules. It takes and returns domain models —
  no `Request`, no FastAPI types, no driver types.
- **`repository/`** holds all persistence, behind a `Protocol`.

**The repository `Protocol` is declared in `service/`, not in `repository/`.**
The consumer owns the interface: the service says what it needs, and an
implementation satisfies it structurally without either importing the other.
`repository/memory/` is the only implementation today; a Postgres one would be a
sibling package chosen by `__main__.py`, and nothing else would change.

{% if include_examples %}### One resource depending on another

`orders` references `widgets`, which is the case a template has to show. The
order service declares a `WidgetLookup` Protocol with the single method it
needs, and `Widgets` satisfies it without knowing orders exist. Copy that rather
than depending on the whole neighbouring service.

{% endif %}## API

| method | path | status | notes |
| --- | --- | --- | --- |
{% if include_examples %}| GET | `/widgets` | 200 | every widget, oldest first |
| GET | `/widgets/{id}` | 200, 404 | |
| POST | `/widgets` | 201, 409, 422 | 409 on a duplicate name |
| GET | `/orders` | 200 | every order, oldest first |
| GET | `/orders/{id}` | 200, 404 | |
| POST | `/orders` | 201, 400, 422 | 400 if the widget does not exist |
{% endif %}| GET | `/openapi.json` | 200 | OpenAPI 3.1, generated from the handlers |
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

FastAPI's own 422 body is `{"detail": [...]}`, which is not RFC 9457; a
`RequestValidationError` handler replaces it. A shape violation returns **422**,
which is what both FastAPI and the Go service's huma do by default. A
business-rule violation returns **400** — including ordering a widget that does
not exist, which is a bad *reference* in a well-formed request to a route that
does exist, not a missing `/orders` resource. Every response carries an
`X-Request-Id` header, echoing the inbound one if there was one.

## Configuration

Precedence, lowest to highest:

```
defaults in code  <  config/config.yaml  <  config/config.local.yaml  <  environment
```

Environment variables are `{@ env_prefix @}_` + the config path upper-cased, with `__`
between levels and the key's own underscores preserved:

```
server.read_timeout  ->  {@ env_prefix @}_SERVER__READ_TIMEOUT
logging.format       ->  {@ env_prefix @}_LOGGING__FORMAT
```

**`.env` files are not read by the application.** pydantic-settings defaults to
a four-source chain that includes them, which lets a `.env` silently beat YAML;
`settings_customise_sources` returns exactly `(init, env, yaml)`. Loading `.env`
into the environment is direnv's job, and `.envrc` does it.

`make config` prints the effective values and names the source of each. An
invalid configuration fails at startup and reports **every** bad field at once.

## Ports and shutdown

The API listens on `server.port` and health checks on `server.admin_port`.
Setting them equal collapses both onto one listener, and is supported.

**`uvicorn.run()` is deliberately not used.** It builds exactly one `Server` and
exposes no handle on which to neutralize signal capture, so with two listeners
they race on the same handlers and the process dies before it drains.
`__main__.py` constructs `uvicorn.Config` and `uvicorn.Server` per listener and
owns SIGTERM itself.

`log_config=None` and `access_log=False` are set on each `Config`. **Losing
either silently restores uvicorn's own log handlers**, and the symptom appears
nowhere near the change that caused it.

Run it with `python -m {@ package_name @}`, never the `uvicorn` CLI — the CLI configures
logging before importing the app.

## Metrics

On the admin port at `/metrics`:

| metric | labels |
| --- | --- |
| `http_server_requests_total` | `method`, `route`, `status` |
| `http_server_request_duration_seconds` | `method`, `route`, `status` |
| `http_server_active_requests` | `method` |

Buckets are OpenTelemetry's advisory set, declared literally rather than taken
from the library's defaults. `disable_created_metrics()` suppresses the
`_created` gauge each counter would otherwise carry — through the API, not the
`PROMETHEUS_DISABLE_CREATED_SERIES` environment variable, because configuration
is read in exactly one place and this is not it.

`route` is the registered template, never the concrete path, and an unrouted
request is labelled `<unmatched>`. It is read from `scope["route"]` *after* the
router has run: resolving it early by re-running the match was tried and
rejected, because FastAPI wraps included routers in a private type whose shape
changes between releases. That is also why the in-flight gauge carries no
`route` label — and OpenTelemetry's own convention omits it for the same reason.

**`service_owner` is not a label.** It lives on `target_info`, joinable with
Prometheus 3's `info()`.

**Phase 1 assumes a single worker.** `prometheus_client`'s multiprocess mode
needs `PROMETHEUS_MULTIPROC_DIR` and `multiprocess_mode="livesum"`; without
them, more than one uvicorn worker makes the in-flight gauge report one worker's
view rather than the process group's.

## Tracing

OpenTelemetry, wired only in `observability.py`.

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

`trace_id` and `span_id` are added by a loguru patcher rather than at call sites, and are **omitted entirely when there
is no span** — never empty, never fabricated. An empty `trace_id` in an
aggregator is worse than an absent one: it looks like a trace that exists and
cannot be found.

**This service owns identity and defers on transport.** `OTEL_SERVICE_NAME` and
`OTEL_RESOURCE_ATTRIBUTES` are deliberately ignored — logs and spans disagreeing
about `service` or `env` would break the error-to-trace path. The one ecosystem
variable honoured is `OTEL_EXPORTER_OTLP_ENDPOINT`, read as an explicitly
enumerated fallback inside `observability.py` when `otlp_endpoint` is unset, so
`make config` still names its source.

The ASGI instrumentation is installed with `exclude_spans=["receive", "send"]`.
Without it, every request also produces an `http send` and an `http receive`
child span describing the ASGI protocol rather than anything a reader of the
trace cares about.

## Updating from the template

`.copier-answers.yml` records the template version and every answer given. To
pull in later template changes:

```sh
copier update            # re-runs the questions with your answers as defaults
copier update --defaults # keeps every answer as recorded
```

Copier merges template changes into the working tree and leaves conflicts as
git-style markers. Commit before updating so the diff is reviewable.

Everything in this repository is yours to edit after generation — the update is
a three-way merge, not an overwrite.

## Not built

Authentication is deliberately deferred to a gateway: the middleware chain has a
named empty slot for it, and the service warns at startup when `env != local`
and none is registered.
