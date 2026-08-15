# widget-svc (Python)

A small HTTP service: two layers, structured logging, RFC 9457 errors, and an
OpenAPI 3.1 document served with Swagger UI.

This is one of two reference implementations in [Mint](../README.md). The Go
service exposes the same API and the same Makefile targets; a client should not
be able to tell which one it is talking to.

## Quick start

```sh
direnv allow      # picks up the pinned Python and uv from .tool-versions
uv sync
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

```
src/widget_svc/__main__.py      composition root — wires everything, owns signals
src/widget_svc/config.py        the ONLY place that reads env vars or files
src/widget_svc/log.py           the two log tiers
src/widget_svc/errors.py        the domain error taxonomy
src/widget_svc/service.py       business logic and the widget store
src/widget_svc/api/             routers, middleware, problem+json, health
config/config.yaml              checked-in defaults
```

This is *not* the Go service's directory tree transliterated. Go gets
`cmd/` and `internal/` because that is what Go does; Python gets a flat `src/`
package with an `api/` subpackage because that is what Python does. What matches
between the two is the outside contract, not the file layout.

### The layer rule

- **`api/`** parses a request, validates its *shape* (FastAPI does that from the
  type annotations), calls the service, and returns a model. No business logic.
- **`service.py`** holds all business rules and the error taxonomy. It takes and
  returns plain pydantic models — no `Request`, no FastAPI types, no driver
  types.

Widgets are held in memory. A real service would define a repository protocol in
`service.py`, implement it elsewhere, and inject it from `__main__.py`.

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
business-rule violation returns **400**. Every response carries an
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

Run it with `python -m widget_svc`, never the `uvicorn` CLI — the CLI configures
logging before importing the app.

## Not built yet

Metrics, OpenTelemetry tracing, and a generated `llms.txt`. The seams are in
place: handlers and service methods are `async`, request-scoped log fields ride
on contextvars (which is what OTel uses), the middleware chain has named empty
slots for tracing, metrics and auth, and the access log already records the
route *template* rather than the concrete path.
