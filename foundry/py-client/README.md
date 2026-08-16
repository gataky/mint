# mint-client (Python)

The outbound half of a Mint service.

The inbound half is a middleware chain that assigns a correlation ID, continues
a trace, records metrics, enforces a deadline and returns RFC 9457 on failure.
This library is the same chain pointing outwards, so a request keeps all of it
as it crosses to the next service.

## This is a library, not a template

The distinction matters, because everything else in
[`foundry/`](../../README.md) works the other way.

`foundry/go-service/` and `foundry/py-service/` are **reference services**: they
are copied into `templates/`, parameterised, and rendered into a new service by
Copier. The generated service then owns that code outright.

**This package is never rendered, never copied, and never parameterised.** It is
installed — `mint-client` in a `pyproject.toml` — by any project that calls a
Mint service, whether or not that project was itself minted from this repo. Its
consumers are downstream codebases, so it is versioned and released on its own
cadence and its public API is a compatibility promise in a way that template
source never is.

Two things follow, and both are enforced by `make lint`:

- It reads **no** environment variables and **no** files. A service is allowed
  exactly one reader; a library gets zero.
- It depends on the OpenTelemetry **API**, never the SDK. The application owns
  the tracer provider.

## Quick start

```sh
direnv allow      # picks up the pinned Python and uv from .tool-versions
uv sync
make test
```

```python
from mint_client import Client, UpstreamNotFoundError

client = Client.for_peer(config.clients, "widget-svc", metrics=client_metrics)

widget = await client.get("/widgets/abc", into=Widget, route="/widgets/{id}")
```

That call carries a `traceparent` naming its own client span, the inbound
`X-Request-Id`, and whatever is left of the request's deadline — none of which
the call site mentions.

## Commands

| target | what it does |
| --- | --- |
| `make build` | builds a wheel into `bin/` |
| `make test` | unit tests with a coverage summary |
| `make test-integration` | tests marked `integration` |
| `make lint` | ruff, ruff format --check, mypy --strict, and two discipline checks |
| `make fmt` | ruff format and ruff --fix, in place |
| `make clean` | removes `bin/` and the tool caches |
| `make help` | this list, generated from the Makefile |

`run` and `config` are absent on purpose: a library has nothing to boot and no
configuration of its own to print. Stubs that printed "n/a" would make
`make help` lie about what exists.

## Layout

```
src/mint_client/client.py          the client — one class
src/mint_client/errors.py          what a call raises when it does not return
src/mint_client/context.py         the deadline and correlation ID, on contextvars
src/mint_client/config.py          the `clients` config schema — and nothing that reads it
src/mint_client/observability.py   the three client metrics
src/mint_client/problem.py         RFC 9457, parsed rather than guessed at
src/mint_client/resilience.py      the named, empty retry slot
src/mint_client/duration.py        Go-style duration strings, as a pydantic type
```

## What is automatic

**Trace context.** A `CLIENT` span per attempt, with W3C context injected
*inside* it — so the peer's server span is a child of the call, not of the
request that caused the call. Injecting before the span starts is an easy
mistake that is invisible locally and produces a trace where every upstream span
hangs off the server span as an unrelated sibling.

Span names are `{METHOD}`, or `{METHOD} {route}` when a `route=` template is
given — matching how the server side names its spans. **The concrete path is
never a span name.** Attributes follow OpenTelemetry's HTTP client convention:
`http.request.method`, `server.address`, `server.port`, `url.full` (with any
credentials redacted), `http.response.status_code`, `peer.service`.

For a **client** span any 4xx is an error. For a **server** span only 5xx is — a
404 there is the server working correctly. The asymmetry is in the spec and is
easy to get backwards.

**Correlation ID.** `X-Request-Id` is forwarded from the inbound request, so one
ID spans a whole fan-out and one grep finds all of it. **Never sent empty** — an
empty ID downstream looks like a correlation ID that exists and cannot be found.

**The deadline.** See below.

**RFC 9457.** A failure's `problem+json` body is parsed onto the exception. The
parse never raises: a client that crashed while handling an error response would
turn a recoverable upstream failure into an unrecoverable local one. A peer that
did not send one leaves `.problem` as `None`, never as an empty `Problem` —
"told us nothing" and "does not speak RFC 9457" are different facts.

## Deadline propagation

The server gives each request a `request_timeout` budget. A call that opened its
own independent 5s timeout inside a 10s request could overrun it, and three
sequential calls certainly would — the handler is killed mid-flight and the
client sees a 504 with no indication which upstream was slow.

So the budget is recorded once, by whatever owns it, and every call below takes
**what is left**:

```python
with bind_deadline(config.server.request_timeout.total_seconds()):
    await client.get("/widgets")  # gets the remainder, not a fresh 5s
```

- A nested block may **tighten** the deadline, never widen it. One
  over-generous sub-timeout cannot escape the request budget.
- A call with **no budget left fails without dialling**. Opening a connection
  certain to be abandoned costs the peer a worker and this process a socket.
- The deadline is **monotonic**, not wall-clock: an NTP step during a request
  must not extend or collapse a timeout.

`TimeoutConfig.total` is what actually bounds a call, enforced with
`asyncio.timeout`. The per-phase timeouts each restart with their phase, so a
peer trickling one byte every four seconds satisfies a 5s read timeout forever.

## Errors

**The taxonomy is deliberately not the service's domain taxonomy.** It would
have been shorter to raise `NotFoundError` on an upstream 404 and let it fall
through the caller's `api/problem.py` untouched — and it would be wrong. Your
404 means *the resource you asked me for does not exist*. An upstream's 404
means *a thing I depend on is missing*, which is frequently a 500, sometimes a
400, and only occasionally a 404.

So the client says what happened on the wire and the caller's `service/` layer
decides what it means:

```python
try:
    widget = await client.get(f"/widgets/{widget_id}", into=Widget)
except UpstreamNotFoundError as exc:
    raise InvalidError(f'no widget with id "{widget_id}"') from exc
```

That translation is business logic, and business logic lives in `service/`.

```
MintClientError
├── UnknownPeerError            a peer not in the registry — raised at startup
├── ResponseValidationError     2xx, in a shape that is not what was asked for
├── TransportError              no response; the peer may or may not have run
│   ├── ConnectError            DNS, TCP, TLS, proxy — it definitely did not run
│   └── DeadlineExceededError   out of time, or out of budget before dialling
└── UpstreamError               a response, and it was a failure
    ├── UpstreamClientError     4xx
    │   ├── UpstreamInvalidError        400
    │   ├── UpstreamUnauthorizedError   401
    │   ├── UpstreamForbiddenError      403
    │   ├── UpstreamNotFoundError       404
    │   ├── UpstreamConflictError       409
    │   ├── UpstreamUnprocessableError  422
    │   └── UpstreamRateLimitedError    429
    └── UpstreamServerError     5xx
        └── UpstreamUnavailableError    502, 503, 504
```

The split that matters operationally is `TransportError` vs `UpstreamError`: a
transport failure means the peer **may** have applied the write, and an upstream
error means it definitely ran. An unmapped status is still catchable by its 4xx
or 5xx parent rather than arriving as a bare `UpstreamError` nobody handles.

Every `UpstreamError` carries `.status`, `.problem`, `.peer`, `.request_id` (the
peer's, for chasing the failure in their logs) and `.retry_after`.

## Configuration

**This package reads no environment variables and no files, and it never will.**
py-service enforces "configuration is read in exactly one place" with a lint
rule; a library reading its own environment would defeat that rule from outside
the tree it checks, and `make config` would stop naming the source of every
value. `make lint` here fails on `os.environ` anywhere in `src/`.

The package owns the *schema*; the service owns the *loading*:

```python
class Config(BaseSettings):
    ...
    clients: ClientsConfig = ClientsConfig()
```

which yields, with no extra work:

```yaml
clients:
  timeout:
    total: 5s
    connect: 2s
  peers:
    parts_svc:
      base_url: http://parts-svc:8080
      timeout:
        total: 2s
```

```
clients.peers.parts_svc.base_url  ->  MINT_CLIENTS__PEERS__PARTS_SVC__BASE_URL
```

**Peer keys use underscores** — `parts_svc`, not `parts-svc`. This is forced,
not chosen: `__` separates config levels in a variable name, so the key must
survive being lower-cased, and a hyphen cannot appear in a shell variable name
at all. Lookup normalises hyphens, so calling code may spell it either way, and
`PeerConfig.name` keeps the real DNS name for labels and span attributes.

**Declaring peers in config is what makes a typo fail at startup** rather than
at 3am under load. `Client.for_peer` raises `UnknownPeerError` naming the peers
that *do* exist.

## Metrics

The client-side mirror of the service's three, `client` where it says `server`:

| metric | labels |
| --- | --- |
| `http_client_requests_total` | `method`, `peer`, `status` |
| `http_client_request_duration_seconds` | `method`, `peer`, `status` |
| `http_client_active_requests` | `method`, `peer` |

**The registry comes from the service; the definitions come from here.** That
division is most of why this is a shared library: a registry per service is
required — the process-global one cannot be built twice, so two services could
not be constructed in one test session — but a different metric *name* per
service would mean no dashboard could span two of them. Construct one
`ClientMetrics` per service and share it across every `Client`; the `peer` label
is what separates them.

`peer` is the logical service name, **never a host and never a URL** — the same
unbounded-cardinality rule as the server's route template, in outbound clothing.

Unlike the server's in-flight gauge, this one *can* carry the peer: the
destination is known before the call starts, whereas a route template is not
known until the router has run.

A call that produced no response is recorded under the sentinel status
`<error>`, following the convention `<unmatched>` already set. Inventing a
synthetic 503 would be worse — it would be indistinguishable in a dashboard from
a real 503 the peer actually sent. **Which kind** of transport failure it was
lives on the span as `error.type`, not in a metric label; that is a deliberate
v1 limit.

## Transport

`httpx2`, async only. Async-only matches the service's execution model — every
caller is inside an async handler — and one code path is one thing to test.

`httpx2.alias_httpx()` is **never called**: it is documented as being for
applications migrating from `httpx`, and explicitly not for libraries. It is
also why the tracing here is hand-written rather than using
`opentelemetry-instrumentation-httpx`, which patches `httpx`, not `httpx2`.

Two defaults worth knowing:

- **Redirects are not followed.** Between services a redirect is almost always a
  misconfiguration, and following it silently converts a loud 307 into a working
  call that costs two round trips forever.
- **`trust_env=False`.** Honouring `HTTP_PROXY` and friends would let a variable
  nobody declared change where a call goes — the same disease `make config`
  exists to cure.

One `Client` per upstream, built once at startup and shared: it owns a
connection pool, and building one per call throws away every keep-alive
connection. It is bound to one peer on purpose — a client that could address
anywhere would have no honest `peer` label, no single timeout policy, and no
pool whose limits mean anything.

## Binding a response

Without `into=` you get the `Response` and call `.json()` yourself. With it, the
body is validated into that type:

```python
res = await client.get("/widgets")  # Response
widget = await client.get("/widgets/w1", into=Widget)  # Widget
widgets = await client.get("/widgets", into=list[Widget])  # list[Widget]
counts = await client.get("/counts", into=TypeAdapter(dict[str, int]))
```

The overloads are typed, so `into=Widget` statically returns `Widget` — checked
by mypy over `tests/`, which is the assertion. `TypeAdapter`s are cached per
type; building one compiles a validator, and doing that per call would pay for
it on every request forever.

A body that does not fit raises `ResponseValidationError` — not a transport
fault and not a local bug, but an upstream contract violation. It is the error
that means "redeploy the other service".

## Not built yet

- **Retries, backoff, and circuit breaking.** `resilience.py` is a named, empty
  slot — the same device as the empty auth slot in the service's middleware
  chain. `Client._send_once` is a separate method from `Client._send` for
  exactly this reason: a retry policy becomes a loop in `_send` and nothing else
  changes, and the per-attempt span stays per-attempt so a retried call reads as
  sibling spans rather than one long span that hides the retries.

  A retry is only safe when the call is idempotent, and the client cannot tell.
  Worse, the failure most worth retrying — a read timeout — is exactly the one
  where the peer may already have applied the write. That is not an argument
  against retrying; it is an argument that the policy belongs to whoever knows
  the semantics.

- **A worked example against a running service.** `service.orders.WidgetLookup`
  in py-service is already the right shape for one: a `RemoteWidgets` satisfying
  that Protocol over HTTP would swap in at a composition root with nothing else
  changing. That would be a demonstration, not a dependency — py-service does
  not import this package.

- **A Go counterpart.** Mint's premise is that the two services are
  indistinguishable from outside; a Go client owes the same header names, metric
  names and span names as this one. Nothing here is Python-specific by design.

- **`error.type` as a metric label**, distinguishing a timeout from a connection
  refusal without opening a trace.

- **Publishing.** There is no release process yet — no tag, no registry, no
  version policy. Consumers currently install it from a path or a git ref.
