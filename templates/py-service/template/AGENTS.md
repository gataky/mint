# AGENTS.md — {@ service_name @} (Python)

Context for coding agents working in this service. Read `README.md` first for
what the service does; this file is about how to change it without breaking the
things that are deliberate.

## Commands

```sh
make run      # boot
make test     # unit tests + coverage
make lint     # ruff, ruff format --check, mypy --strict, config-discipline check
make fmt      # ruff format and --fix in place
make config   # effective config, with the source of each value
make help     # every target
```

Tooling is pinned in `pyproject.toml`'s dev group. Do not `pip install` linters
globally — use `uv run <name>`.

## Architecture

Three layers, plus a composition root. Dependencies point inward: `domain/`
imports nothing else in the service.

```
src/{@ package_name @}/__main__.py         wires everything; owns signals; no business logic
src/{@ package_name @}/domain/             entities and the error taxonomy
src/{@ package_name @}/service/            business rules; declares the repository Protocols
src/{@ package_name @}/repository/memory/  repository implementations
src/{@ package_name @}/api/                routers, middleware, problem+json, health
src/{@ package_name @}/config.py           the ONLY place that reads env vars or files
src/{@ package_name @}/log.py              the two log tiers
src/{@ package_name @}/observability.py    metrics registry and tracer provider
```

**One module per resource in each layer.**{% if include_examples %} `widgets.py` and `orders.py` appear
in all four; that is the convention, not a coincidence.{% else %} No resource ships with this
service yet; the four layers are empty and waiting for the first one.{% endif %}

The repository `Protocol` is declared in `service/` — the consumer owns the
interface — and satisfied structurally by `repository/memory/`.

## Adding a resource

Four modules and one line, in this order:

1. `domain/<name>.py` — the entity and its input model. Export both from
   `domain/__init__.py`.
2. `service/<name>s.py` — the repository `Protocol` this service needs, and the
   business rules. Raise domain errors, never HTTP statuses.
3. `repository/memory/<name>s.py` — the implementation.
4. `api/<name>s.py` — the router.
5. Wire it in `__main__.py` and `include_router` it in `create_api`.

If the new resource needs an existing one, declare a **narrow Protocol** for
just the methods you use{% if include_examples %} — see `service.orders.WidgetLookup` —{% endif %} rather than
depending on the whole neighbouring service.

## Adding an operation

1. Add the business logic to that resource's module in `service/`, raising a
   domain error from `domain/errors.py` (`NotFoundError`, `InvalidError`,
   `ConflictError`) — never an HTTP status.
2. Add the route to that resource's module in `api/`. FastAPI derives
   placement, validation and the OpenAPI schema from the type annotations.
3. Document error responses with `responses={404: _PROBLEM}` so they appear in
   `/openapi.json`.

```python
@router.delete(
    "/{id}",
    operation_id="widgets.delete",
    summary="Delete a widget",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={status.HTTP_404_NOT_FOUND: _PROBLEM},
)
async def delete_widget(
    widgets: WidgetsDep,
    widget_id: Annotated[str, Path(alias="id", min_length=1, max_length=64)],
) -> None:
    await widgets.delete(widget_id)
```

## Don't do this

- **Don't read an environment variable outside `config.py`.** `make lint` fails
  on it. `make config` is only truthful because there is one reader.
- **Don't re-enable pydantic-settings' default source chain.** It includes
  `.env`, which silently beats YAML. `settings_customise_sources` returns
  exactly `(init, env, yaml)`.
- **Don't name an HTTP status in `service/` or `domain/`.** Raise a category;
  the transport owns the mapping table in `api/problem.py`.
- **Don't let `domain/` import anything else in the service.** It is the
  innermost layer; an import pointing outward from it is the layering breaking.
- **Don't declare a repository `Protocol` in `repository/`.** The consumer owns
  it: it belongs in the service module that calls it.
- **Don't depend on a whole neighbouring service.** Declare a narrow Protocol
  with the methods you actually use.
- **Don't let FastAPI's stock 422 body through.** It is `{"detail": [...]}`,
  not RFC 9457. The `RequestValidationError` handler replaces it.
- **Don't let a driver error or traceback reach the response.** Internal errors
  are logged in full and returned as a generic message.
- **Don't let a Python keyword rename a path parameter.** The route template is
  part of the API contract: `/widgets/{id}` is declared with
  `Path(alias="id")` so the Python name does not shadow the builtin.
- **Don't call `uvicorn.run()` or use the `uvicorn` CLI.** Both break shutdown
  and logging; see the README for why. `__main__.py` owns the servers.
- **Don't drop `log_config=None` or `access_log=False`** from a `uvicorn.Config`.
  Losing either silently restores uvicorn's own log handlers.
- **Don't reorder the middleware chain** in `api/__init__.py`. The order is
  deliberate and documented in `api/middleware.py`; auth in particular sits
  *inside* the access log.
- **Don't label a metric, span or log field with a concrete path.** Use
  `resolve_route(scope)`, the route template; an unrouted request is
  `<unmatched>` so a flood of random URLs cannot create unbounded series.
- **Don't register a literal subpath after a parameterised one.** Starlette
  matches in registration order, unlike Go's ServeMux, so `/widgets/search`
  must come before `/widgets/{id}` or it is swallowed.
- **Don't build a tracer provider outside `observability.py`.** It is installed
  globally once, at startup, by the composition root.
- **Don't skip `tracing.shutdown()` on exit.** The spans for the last requests
  served are still in the batch processor's queue and vanish silently otherwise.
- **Don't drop `exclude_spans=["receive", "send"]`** from the FastAPI
  instrumentation. Without it every request emits two extra ASGI-protocol child
  spans that describe the ASGI protocol rather than the request.

## Staying in step with the template

This service was minted from `{@ _copier_answers['_src_path'] @}`, and
`.copier-answers.yml` records the version and the answers. `copier update`
merges later template changes in; it is a three-way merge, so local edits
survive and conflicts arrive as git-style markers.

Two things follow from that:

- **Every file here is yours to edit.** Nothing is regenerated behind your back.
- **A change worth having in every service belongs upstream.** Fixing it here
  and in the template separately is how the two drift.

Sibling services minted from the Go template expose the same API on purpose:
route paths, status codes, the `problem+json` body shape, log field names,
config precedence and env var names, metric names and label keys, span names,
and the `make help` target list. Internal module layout, error message wording,
JSON key order, and test names are language-idiomatic and deliberately differ.
