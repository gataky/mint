# AGENTS.md — widget-svc (Go)

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
cmd/widget-svc/main.go       wires everything; owns signals; no business logic
internal/domain/             entities and the error taxonomy
internal/service/            business rules; declares the repository interfaces
internal/repository/memory/  repository implementations
internal/transport/http/     handlers, middleware, error mapping, listeners
internal/config/             the ONLY place that reads env vars or files
internal/logging/            the two log tiers
internal/observability/      metrics registry and tracer provider
```

**One file per resource in each layer.** `widget.go` and `order.go` appear in
all four; that is the convention, not a coincidence.

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
5. Wire it in `cmd/widget-svc/main.go` and call `register<Name>s` in
   `NewAPI`.

If the new resource needs an existing one, declare a **narrow interface** for
just the methods you use — see `service.WidgetLookup` — rather than depending on
the whole neighbouring service.

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
4. Mirror the change in the Python service.

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
  every response body, which the Python service does not emit.
- **Don't build a tracer provider outside `internal/observability`.** It is
  installed globally once, at startup, by the composition root.
- **Don't skip `tracing.Shutdown` on exit.** The spans for the last requests
  served are still in the batcher's queue and vanish silently otherwise.

## Keeping the two services identical

What must match is the outside contract: route paths, status codes, the
`problem+json` body shape, log field names, config precedence and env var
names, metric names and label keys, span names, and the `make help` target
list. `make compare` from the repo root boots both and diffs all of it, but
nothing runs it for you — changing one service means changing the other by
hand.

What deliberately does *not* have to match: internal package layout, error
message wording, JSON key order, and test names. Each language does what is
idiomatic for it.
