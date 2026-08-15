# Mint

Two reference microservices — one Go, one Python — that expose the **same API**
and the **same Makefile**. A client cannot tell which one it is talking to; a
developer moving between them does not have to relearn anything.

Once these are right, they become [Copier](https://copier.readthedocs.io/)
templates for minting new services. **That step has not been taken yet** — see
[Where this is going](#where-this-is-going).

```
mint/
├── go-service/       Go 1.26 · net/http · huma · koanf · slog + tint · OTel
└── python-service/   Python 3.14 · FastAPI · uvicorn · pydantic-settings · loguru · OTel
```

## Quick start

```sh
make -C go-service run          # :8080, admin :9080
make -C python-service run      # same ports — run one at a time
```

Both default to the same ports on purpose: they are the same service. To run
them side by side, override one:

```sh
MINT_SERVER__PORT=8081 MINT_SERVER__ADMIN_PORT=9081 make -C python-service run
```

## Commands

Every target below exists in **both** services with the same name and the same
behavior:

| target | what it does |
| --- | --- |
| `run` | boots the service |
| `build` | produces the runnable artifact |
| `test` | unit tests with a coverage summary |
| `test-integration` | the tagged/marked tests |
| `lint` | linter + type check + the "no env vars outside config" check |
| `fmt` | formats in place |
| `config` | prints the effective config and where each value came from |
| `clean` | removes build artifacts |
| `help` | self-documents by parsing `##` comments |

From the repo root, `make test`, `make lint`, `make fmt` and `make build` fan
out to both.

```sh
make compare   # boots both and diffs what they return, request by request
```

## What is guaranteed to match

Only the things something outside the service consumes:

- **The API** — route templates, methods, status codes, and response bodies.
- **The error contract** — RFC 9457 `application/problem+json`, with `type`,
  `title`, `status`, `detail` and `instance` on every error.
- **Log field names** in both tiers, and the level vocabulary
  (`debug`/`info`/`warn`/`error` — Python's `warning` and `critical` are
  normalized).
- **Metric names and label keys**, compared as parsed families over a
  Mint-owned allowlist — never raw text, because Python renders `le="1.0"`
  against Go's `le="1"` and the two expose different runtime collectors.
- **Trace propagation** — W3C `traceparent` in, `trace_id` and `span_id` on
  every log line emitted inside a span, and `{method} {route}` span names.
- **Config precedence and environment variable names.**
- **The Makefile target list.**

## What deliberately does not match

Packaging, error message wording, JSON key order, and test names. Each language
does what is idiomatic for it:

- Go gets `cmd/` and `internal/`, because that is Go's convention.
- Python gets a `src/widget_svc/` package, because that is Python's.

Writing Python that looks like Go produces bad Python. The contract is the API,
not the file tree.

## Service structure

The *layers* do match, because they are the thing a template is for. Both
services are organised the same way, **one file per resource in every layer**,
so a second and third resource have an obvious home:

```
domain/       entities and the error taxonomy — imports nothing else
service/      business rules; declares the repository interfaces it needs
repository/   implementations of those interfaces (in-memory today)
transport/    handlers, middleware, error mapping
```

Dependencies point inward. The repository interface is declared in the *service*
package that consumes it, not in the repository package — so a Postgres
implementation lands as a sibling of `memory` without touching the service.

Two example resources ship: `widgets`, and `orders`, which references widgets.
The second one is there on purpose — with one example you cannot tell what is
the pattern and what is the resource. `orders` also shows how a resource depends
on another one: a narrow interface naming just the methods it needs, rather than
a dependency on the whole neighbouring service.

Persistence is in-memory. The same implementation is used at runtime and in
tests, so the thing the tests exercise is the thing that runs.

## Configuration

Precedence, lowest to highest, identical in both:

```
defaults in code  <  config/config.yaml  <  config/config.local.yaml  <  environment
```

Environment variables are `MINT_` + the config path upper-cased, with `__`
between levels and the key's own underscores preserved:

```
server.read_timeout  ->  MINT_SERVER__READ_TIMEOUT
logging.format       ->  MINT_LOGGING__FORMAT
```

Two decisions worth keeping:

- **`__`, not `_`, between levels.** Single-underscore nesting cannot
  distinguish `server.read_timeout` from `server.read.timeout`.
- **A constant `MINT_` prefix, not the service name.** Kubernetes injects
  `{SVCNAME}_PORT` into every pod, so `WIDGET_SVC_PORT` would arrive as
  `tcp://10.0.162.149:8080`.

`make config` prints the effective configuration and names the source of every
value. Its output is identical between the two services.

## One-time machine setup

```sh
brew install asdf direnv          # or your platform's equivalent
asdf plugin add golang && asdf plugin add python && asdf plugin add uv
asdf install                      # reads .tool-versions
```

Add direnv's hook to your shell, then `direnv allow` in each service directory.

## Where this is going

**Built:** config, two log tiers, the error contract, the HTTP transport, health
endpoints, Prometheus metrics, OpenTelemetry tracing, graceful shutdown,
OpenAPI 3.1 with Swagger UI, tests, Makefiles, asdf and direnv.

**Next, in rough order:**

1. **A conformance test** — `scripts/compare.sh` is a script you read the output
   of, not a test suite. Promoting it to something that runs in CI is a
   deliberate later step.
2. **Copier templates** — parameterize `service_name`, `module_path` /
   `package_name`, ports and owner, and move both trees under `templates/`.

**Deliberately not built:** authentication (expected at a gateway; the
middleware chain has a named empty slot and both services warn at startup when
`env != local`), Dockerfiles, CI, and Kubernetes manifests.

A longer specification with more of the reasoning — including findings that are
still worth reading — is in `prompt.md`. It describes a considerably more
elaborate system than this one; where the two disagree, this repo is what was
actually built and the spec is aspirational.
