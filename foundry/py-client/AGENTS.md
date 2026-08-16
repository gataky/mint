# AGENTS.md — mint-client (Python)

Context for coding agents working in this library. Read `README.md` first for
what it does; this file is about how to change it without breaking the things
that are deliberate.

## Commands

```sh
make test     # unit tests + coverage
make lint     # ruff, ruff format --check, mypy --strict, two discipline checks
make fmt      # ruff format and --fix in place
make help     # every target
```

Tooling is pinned in `pyproject.toml`'s dev group. Do not `pip install` linters
globally — use `uv run <name>`.

There is no `make run` and no `make config`. A library has nothing to boot and
no configuration of its own to print.

## Architecture

One class, and the parts it needs.

```
src/mint_client/client.py          the client
src/mint_client/errors.py          the exception taxonomy
src/mint_client/context.py         deadline + correlation ID, on contextvars
src/mint_client/config.py          the `clients` schema — nothing that reads it
src/mint_client/observability.py   the three client metrics
src/mint_client/problem.py         RFC 9457 parsing
src/mint_client/resilience.py      the named, empty retry slot
src/mint_client/duration.py        Go-style durations as a pydantic type
```

The dependency direction is: `client.py` imports everything; `duration.py` and
`problem.py` import nothing of ours. `config.py` imports `errors.py` for
`UnknownPeerError` and `duration.py` for `Duration`, and nothing else.

## This is a library, not a template

`foundry/go-service/` and `foundry/py-service/` get copied into `templates/`,
parameterised, and rendered into new services. **This package does not.** It is
never rendered, never copied, never parameterised — it is installed as a
dependency by downstream projects that call Mint services.

So the rules in the repo root's `AGENTS.md` about template source do not apply
here. There is no `{@ @}` delimiter, no gated file, no `include_examples`
answer, and nothing in this tree should ever grow one. Do not add this package
to `templates/`.

The consequence that does bite: **the public API is a compatibility promise.**
Template source can change freely because a generated service owns its copy;
this package's consumers upgrade it. Renaming an exception or changing a
default is a breaking change for someone.

## Two more rules follow from that

**It reads no environment variables and no files.** `make lint` fails on
`os.environ` anywhere in `src/`. The services allow exactly one reader, in
`config.py`; a library gets zero, because a value it read from the environment
would enter a service's behavior without that service's `make config` being able
to name its source.

**It depends on the OpenTelemetry API, never the SDK.** `make lint` fails on an
`opentelemetry.sdk` import in `src/`. A library records spans against whatever
provider the application installed; importing the SDK would let it drag in a
second tracer implementation and would imply it may configure one. The SDK is a
*test* dependency — `tests/conftest.py` installs a real provider so spans can be
asserted on.

## Don't do this

- **Don't read the environment, and don't read a file.** See above. Take it as
  an argument.
- **Don't import `opentelemetry.sdk` under `src/`.** The application owns the
  provider.
- **Don't call `httpx2.alias_httpx()`.** Its own docstring says libraries never
  should — it rewires `import httpx` process-wide for whoever imports us.
- **Don't inject trace context outside the span.** `inject()` must run *inside*
  `start_as_current_span`, or the peer's server span is parented to whatever
  span happened to be current instead of to this attempt. The symptom is a trace
  that looks fine until you try to attribute a slow call to its caller.
- **Don't put a concrete path in a span name or a metric label.** `peer` is the
  logical service name; the span name is `{METHOD}` or `{METHOD} {route}` with a
  route *template*. This is the outbound half of the service's
  `resolve_route` rule.
- **Don't invent a status for a call that got no response.** The `<error>`
  sentinel exists because a synthetic 503 is indistinguishable in a dashboard
  from a real one the peer sent.
- **Don't fabricate a `Problem`.** A peer that sent no problem document leaves
  `.problem` as `None`. An empty `Problem` reads as "the upstream told us
  nothing", which is a different fact.
- **Don't let `parse_problem` raise.** Every path returns `Problem | None`. A
  crash while handling an error response turns a recoverable upstream failure
  into an unrecoverable local one.
- **Don't map an upstream status onto a domain error here.** That is the
  caller's `service/` layer's job, and it is why this taxonomy exists separately.
  See the header of `errors.py`.
- **Don't swallow `CancelledError`.** It means the caller is being torn down;
  converting it into an ordinary exception is how a task refuses to die and a
  graceful shutdown becomes a hard kill. `_transport_error` passes it through.
- **Don't let an unrelated exception become a `TransportError`.** A
  `ZeroDivisionError` in this process is a bug here, not an upstream fault.
  `_transport_error` returns anything it does not recognise untouched.
- **Don't move the budget check outside the instrumented region.** A call
  abandoned for having no time left is still a failed outbound call. Outside,
  a service constantly blowing its deadline shows up as making no calls at all.
- **Don't let a nested `bind_deadline` widen an existing one.** The request
  budget is a ceiling. Widening lets a handler outlive the deadline its own
  server is enforcing.
- **Don't use wall-clock time for the deadline.** It is `time.monotonic()`, so
  an NTP step mid-request cannot extend or collapse a timeout.
- **Don't add retries without reading `resilience.py`.** They go in `_send`, as
  a loop around `_send_once`, so the per-attempt span stays per-attempt.
- **Don't turn on `follow_redirects` or `trust_env`.** Both let something
  undeclared change where a call goes.
- **Don't build a `TypeAdapter` per call.** Building one compiles a validator.
  `_adapter` caches them per type.
- **Don't write an overload that accepts more than the implementation does.**
  mypy rejects it, and it would let a typo through as a keyword argument that
  silently went nowhere. The `request` overloads spell every parameter out
  rather than using `**kwargs`.

## Testing

Every test runs against `httpx2.MockTransport` — the real client, with the
socket replaced. Nothing binds a port, so the suite is deterministic and runs
offline.

- `trace.set_tracer_provider` takes effect **once per process**; a second call
  is ignored with a warning. The provider fixture is session-scoped for that
  reason, with a function-scoped fixture that clears the exporter.
- The span processor is `SimpleSpanProcessor`, not `Batch`. A test that has to
  flush a queue to see its own span is a test that will be flaky.
- A fresh `CollectorRegistry` per test, so metric values start at zero.
- `make lint` runs mypy over `tests/` too. The `into=` annotations at the bottom
  of `test_client.py` are an assertion: if the overloads regress, that file stops
  type-checking.
- **`ruff format` formats Python code blocks inside `README.md`.** A sample in
  the docs is checked like source, so hand-aligned comments in a fenced
  `python` block will fail `make lint` until they are formatted.

## Keeping faith with the services

What must match the inbound side, because something outside consumes both:

- **Header names** — `X-Request-Id`, and W3C `traceparent`/`tracestate`.
- **Metric names and label keys** — `http_client_*` mirroring
  `http_server_*`, with the same duration buckets.
- **Span naming** — `{METHOD} {route}` with the route *template*.
- **The `problem+json` shape** it parses, matching what `api/problem.py` emits.
- **Config precedence and environment variable names** — the schema plugs into
  the service's existing four-layer chain and inherits it.
- **Go-style duration strings**, so both services read the same YAML.

Those are the same contract the two reference services are held to, so a change
to any of them is a change to the Go service — and, because the services are
templated, to `templates/` as well. This package is not templated, but what it
puts on the wire has to keep matching what they read off it.

See the repo root's `AGENTS.md`.
