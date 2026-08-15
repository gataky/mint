# AGENTS.md — {@ service_name @} (Go)

Context for coding agents working in this service. Read `README.md` first for
what the service does; this file is about how to change it without breaking the
things that are deliberate.

## Commands

```sh
make run      # boot
make test     # unit tests + coverage
make lint     # vet, golangci-lint, config-discipline check
make fmt      # gofumpt in place
make config   # effective config, with the source of each value
make help     # every target
```

Tooling is pinned in `go.mod` as `tool` directives. Do not `go install` linters
globally — use `go tool <name>`.

## Architecture

Three layers, plus a composition root. Dependencies point inward: `domain`
imports nothing else in the service.

```
cmd/{@ service_name @}/main.go       wires everything; owns signals; no business logic
internal/domain/             entities and the error taxonomy
internal/service/            business rules; declares the repository interfaces
internal/repository/memory/  repository implementations
internal/transport/http/     handlers, middleware, error mapping, listeners
internal/config/             the ONLY place that reads env vars or files
internal/logging/            the two log tiers
internal/observability/      metrics registry and tracer provider
```

**One file per resource in each layer.**{% if include_examples %} `widget.go` and `order.go` appear
in all four; that is the convention, not a coincidence.{% else %} No resource ships with this
service yet; the four layers are empty and waiting for the first one.{% endif %}

The repository interface is declared in `internal/service` — the consumer owns
the interface — and satisfied by `internal/repository/memory`.

## Adding a resource

Four files and one line, in this order:

1. `internal/domain/<name>.go` — the entity and its input type.
2. `internal/service/<name>.go` — the repository interface this service needs,
   and the business rules. Return domain errors, never HTTP statuses.
3. `internal/repository/memory/<name>.go` — the implementation.
4. `internal/transport/http/<name>.go` — the operations, and a
   `register<Name>s` function.
5. Wire it in `cmd/{@ service_name @}/main.go` and call `register<Name>s` in
   `NewAPI`.

If the new resource needs an existing one, declare a **narrow interface** for
just the methods you use{% if include_examples %} — see `service.WidgetLookup` —{% endif %} rather than
depending on the whole neighbouring service.

## Adding an operation

Everything about an operation is declared in one `huma.Register` call in that
resource's file under `internal/transport/http/`. The router and
`/openapi.json` both read it, so there is no second place to update.

```go
huma.Register(api, huma.Operation{
    OperationID: "widgets.delete",
    Method:      http.MethodDelete,
    Path:        "/widgets/{id}",
    Summary:     "Delete a widget",
    Tags:        []string{"widgets"},
    Errors:      []int{http.StatusNotFound},
}, func(ctx context.Context, in *deleteWidgetInput) (*struct{}, error) {
    if err := widgets.Delete(ctx, in.ID); err != nil {
        return nil, problem(ctx, err)
    }
    return nil, nil
})
```

1. Add the business logic to that resource's file in `internal/service`,
   returning a domain error from `internal/domain/errors.go` (`NotFound`,
   `Invalid`, `Conflict`, `Internal`) — never an HTTP status.
2. Add input/output structs in that resource's transport file. Placement comes
   from struct tags:
   `path:`, `query:`, `header:`, or a `Body` field. Constraints come from
   `minLength:`, `maxLength:`, `enum:`, `format:`. Descriptions come from `doc:`.
3. Return errors through `problem(ctx, err)`, which maps the category to a
   status and fills in the RFC 9457 fields.

## Don't do this

- **Don't read an environment variable outside `internal/config`.** `make lint`
  fails on it. `make config` is only truthful because there is one reader.
- **Don't name an HTTP status in `internal/service` or `internal/domain`.**
  Return a category; the transport owns the mapping table in `errors.go`.
- **Don't let `internal/domain` import anything else in the service.** It is the
  innermost layer; an import pointing outward from it is the layering breaking.
- **Don't declare a repository interface in `internal/repository`.** The
  consumer owns it: it belongs in the service package that calls it.
- **Don't depend on a whole neighbouring service.** Declare a narrow interface
  with the methods you actually use.
- **Don't return a raw error from a handler.** Route it through `problem(ctx, err)`
  or huma writes a bare 500 with no RFC 9457 fields.
- **Don't let a driver error or stack trace reach the response.** Internal
  errors are logged in full and returned as a generic message.
- **Don't drop `ctx` from a service method signature.** It carries the trace
  context; a method that takes no ctx cannot record a span under the request.
- **Don't log with a package-level logger.** Use `logging.FromContext(ctx)` and
  the `*Context` variants of slog's methods, so `request_id`, `trace_id` and
  `span_id` appear automatically.
- **Don't reorder the middleware chain.** The order in `main.go` is deliberate
  and documented in `middleware.go`; auth in particular sits *inside* logging.
- **Don't label a metric, span or log field with a concrete path.** Use the
  route template from `MuxResolver`; an unrouted request is `<unmatched>` so a
  flood of random URLs cannot create unbounded series.
- **Don't re-enable huma's schema-link transformer.** It injects `$schema` into
  every response body, which a service minted from the Python template does not
  emit — a client must not be able to tell the two apart.
- **Don't build a tracer provider outside `internal/observability`.** It is
  installed globally once, at startup, by the composition root.
- **Don't skip `tracing.Shutdown` on exit.** The spans for the last requests
  served are still in the batcher's queue and vanish silently otherwise.

## Staying in step with the template

This service was minted from `{@ _copier_answers['_src_path'] @}`, and
`.copier-answers.yml` records the version and the answers. `copier update`
merges later template changes in; it is a three-way merge, so local edits
survive and conflicts arrive as git-style markers.

Two things follow from that:

- **Every file here is yours to edit.** Nothing is regenerated behind your back.
- **A change worth having in every service belongs upstream.** Fixing it here
  and in the template separately is how the two drift.

Sibling services minted from the Python template expose the same API on
purpose: route paths, status codes, the `problem+json` body shape, log field
names, config precedence and env var names, metric names and label keys, span
names, and the `make help` target list. Internal package layout, error message
wording, JSON key order, and test names are language-idiomatic and deliberately
differ.
