# Mint — Microservice Template Generator (Go + Python)

> This file is the **specification**. It is the durable statement of what
> Mint must be, and it does not get handed to an agent in one piece.
> Implementation is broken into ordered chunks in `tasks/` — each one
> references the sections here that it implements. Start at
> `tasks/00-bootstrap.md`.

## Goal

Build a **monorepo**, named **Mint**, that generates new microservices in
either Go or Python from a single, consistent set of templates using
[Copier](https://copier.readthedocs.io/) — "minting" a new service from a
template.
A developer should be able to run one command, answer a few prompts, and get a
working service — and once inside the generated repo, the *experience* of
building/running/testing it should feel identical regardless of language.
This extends to AI agents: a coding agent should be able to open a generated
service and orient itself as fast as a human reading its README, and a
running service should be self-describing enough that an agent can learn its
capabilities without a human walking it through them.

Two principles govern everything below. When a decision is ambiguous, resolve
it in favor of these:

1. **One set of facts, several representations.** Any fact that appears in
   more than one place — an operation's name, a log field, a Makefile target,
   a config key — has exactly one authoring location and is generated or
   checked everywhere else. A hand-written description that drifts from
   actual behavior is exactly as bad as a stale Swagger comment.
2. **Guarantees are mechanical, not aspirational.** "Keep these identical"
   is not a requirement; a check that exits non-zero when they diverge is.
   Anywhere this spec says two things must match, there must be something
   in `make parity` or `make test` that fails when they stop matching.

## Scope

**Phase 1 (this spec)**: app code, config, logging, errors, HTTP transport,
health checks, lifecycle, tracing, metrics, generated discovery docs, tests,
Makefile, asdf, direnv.

**Explicitly deferred** — do not build these, but do not preclude them:

| deferred | why it's safe to defer | the seam that keeps it cheap |
| --- | --- | --- |
| Dockerfiles, docker-compose | Phase 2 | empty `docker/` dir, reserved |
| CI pipelines | Phase 2 | empty `.github/workflows/`, reserved |
| Kubernetes manifests | Phase 3 | `service_name` is DNS-label-safe; `service_owner` captured now |
| **MCP server** | adds SDK churn and schema-generation complexity before the core is proven | `internal/transport/http/` is a *sibling* directory, not the only one; the operation registry is transport-agnostic |
| **Authentication / authorization** | expected to land at a gateway or mesh, not per-service | a documented, named slot in the middleware chain — see "Middleware order" |

The last two are deliberate deferrals, not oversights, and each needs an ADR
in `docs/decisions/` saying so. Auth in particular: the middleware chain gets
frozen in Phase 1 and checked for parity, so the place auth *would* go must
be named now, or adding it later means amending the one thing both languages
are validated against.

---

## Repo layout (the template source repo itself)

```
mint/
├── templates/
│   ├── _common/             # language-agnostic template files, included by both
│   │   ├── docs/            # the shared docs/ tree copied into every service
│   │   ├── AGENTS.md.jinja  # rendered skeleton, per docs/agents.md
│   │   └── .gitignore.jinja
│   ├── go-service/          # Copier template for Go services
│   │   ├── copier.yml
│   │   └── template/        # parameterized source tree
│   └── python-service/      # Copier template for Python services
│       ├── copier.yml
│       └── template/
├── docs/
│   ├── architecture.md      # 3-layer architecture, middleware order, error contract
│   ├── logging.md           # the shared log schema (source of truth)
│   ├── config.md            # config precedence rules (source of truth)
│   ├── agents.md            # source of truth for AGENTS.md / discovery scheme
│   ├── testing.md           # the shared testing conventions (source of truth)
│   └── decisions/           # ADRs — every flagged decision lands here
│       └── 0001-<slug>.md
├── tasks/                   # ordered implementation chunks (see tasks/README.md)
├── scripts/
│   ├── parity.sh            # the drift check (see "Parity enforcement")
│   └── verify-template.sh   # generate → build → boot → assert → tear down
├── Makefile                 # mint's own targets: parity, verify, test, lint, fmt, help
├── AGENTS.md                # context for coding agents maintaining THIS repo
├── CLAUDE.md                # symlink to AGENTS.md
├── CHANGELOG.md
└── README.md                # how to generate a new service, how to update templates
```

`templates/_common/` holds only files that are genuinely identical across
languages — the `docs/` tree, the AGENTS.md skeleton, `.gitignore`, the
non-language sections of the README. Both `copier.yml` files pull it in.
Anything that needs a language-specific word in it does *not* belong there;
resist the urge to `[% if language == "go" %]` your way into a single
unreadable template.

---

## Copier mechanics

**Questions.** Both `copier.yml` files ask an identical set, in identical
order:

| question | type | notes |
| --- | --- | --- |
| `service_name` | str | kebab-case, DNS-label-safe (it becomes a k8s name in Phase 3). Validate with a regex — reject anything that isn't `^[a-z][a-z0-9-]{1,38}[a-z0-9]$`. |
| `service_description` | str | one line; lands in README and OpenAPI `info.description` |
| `service_owner` | str | team or squad name — feeds AGENTS.md, a metric label, and Phase 2/3's CODEOWNERS and k8s annotations |
| `repo_url` | str | e.g. `github.com/<org>/<service_name>` |
| `module_path` (Go) / `package_name` (Python) | str | default derived from the answers above: Go `[[ repo_url ]]`, Python `service_name` with `-`→`_`. Validate format. |
| `port` | int | range-checked, 1024–65535 |
| `admin_port` | int | serves `/metrics`, `/healthz`, `/readyz`. Defaults to `port + 1000`. Setting it equal to `port` collapses everything onto one listener — support that, and say so in the help text. |

Every question needs a `help` string, a validator where a bad answer would
produce code that doesn't compile or boot, and a default where one is
derivable. Bad input should fail at prompt time, not at `go build` time.

Set `_min_copier_version` and `_subdirectory: template` explicitly.

**Jinja delimiters.** Override Copier's defaults to `[[ ]]` / `[% %]` /
`[# #]` in both `copier.yml` files. Phase 2 brings GitHub Actions, whose
`${{ }}` collides with Jinja's, and Helm charts after that. Changing
delimiters later means touching every template file — do it now, before
there are any.

**Tasks.** Use `_tasks` for post-generation setup: `git init`, `go mod tidy`
/ `uv sync`, and a final printed next-steps block telling the developer to
run `direnv allow` and then `make run`. A freshly minted service should
require zero manual repair before `make run` works.

**Updates are a first-class workflow.** `copier update` is the entire reason
to use Copier over cookiecutter, and generated services must stay updatable:

- The top-level README documents `copier update` as the supported way to pull
  template improvements into an existing service, including how to handle
  conflicts and what to do with `.copier-answers.yml`.
- Use `_migrations` for changes that can't merge cleanly (a renamed
  directory, a config key that moved).
- Never generate a file the service is expected to heavily edit *and* expect
  to update it later without conflicts. Where a file is meant to be owned by
  the service after generation (handlers, business logic), say so in a
  comment at the top of the file.

**Versioning.** Tag per template, not per repo: `go-service/v1.2.0` and
`python-service/v1.2.0` move independently, so a Python-only fix doesn't bump
the mint mark on every Go service. Document in the README what counts as a
breaking template change (removing a copier question, renaming a directory,
changing a config key) versus additive. Keep `CHANGELOG.md` per template.

**Mint mark.** Each generated service's README surfaces which template and
version it was minted from, sourced from Copier's own answers file
(`.copier-answers.yml`, specifically the `_commit` it already records) rather
than a separately hand-written note, so it can't go stale. Something like:
"Minted from `go-service` @ `v1.2.0`."

Note that `_commit` only renders cleanly if mint is a git repo *with tags* —
so `git init` and tag before running the verification script, and make the
README template degrade gracefully (omit the line entirely, don't render a
half-empty sentence) when `_commit` is absent or untagged.

---

## Generated service layout (what `copier copy` produces)

For **both** languages, generate this shape. Directory names and their
purposes are identical; only file extensions and language idioms differ.
Python nests the same tree under `src/<package_name>/` — `internal/` is not a
Python convention, but keeping the names identical means the mental map
transfers between languages intact, which is the whole point.

```
<service-name>/
├── cmd/<service-name>/main.go   |  src/<pkg>/__main__.py   # composition root only
├── internal/transport/http/     |  src/<pkg>/internal/transport/http/
├── internal/service/            |  src/<pkg>/internal/service/
├── internal/repository/         |  src/<pkg>/internal/repository/
├── internal/config/             |  src/<pkg>/internal/config/
├── internal/logging/            |  src/<pkg>/internal/logging/
├── internal/observability/      |  src/<pkg>/internal/observability/
├── internal/apierror/           |  src/<pkg>/internal/apierror/      # error contract
├── config/
│   ├── config.yaml                 # defaults, checked in
│   └── config.local.yaml.example   # committed; config.local.yaml is gitignored
├── docs/                           # copied from templates/_common/docs/
├── AGENTS.md                       # context for coding agents on this service
├── CLAUDE.md                       # symlink to AGENTS.md
├── .gitignore
├── .tool-versions                  # asdf
├── .envrc                          # direnv
├── Makefile
└── README.md                       # links AGENTS.md, /llms.txt, /openapi.json
```

`internal/transport/http/` is deliberately a *subdirectory* rather than
`internal/transport/`. There is one transport in Phase 1; the nesting is what
makes adding a second one later an addition rather than a refactor.

Tests live beside the code they cover in Go (`*_test.go`) and under `tests/`
in Python, mirroring the package tree — see "Testing" below.

`/llms.txt` and `/openapi.json` aren't tracked as static files in the tree
above — they're generated at build time (see "AI-agent discoverability" and
the `agents-docs` Makefile target) and served by the HTTP transport.

---

## Architecture rules (enforce in both languages)

- **Transport layer**: HTTP handlers only. Parses requests, validates shape
  (not business rules), calls into the service layer, serializes responses.
  No business logic, no direct DB/repository calls.
- **Service layer**: All business logic and validation. Takes plain
  language-native types in/out — no `http.Request`, no FastAPI `Request`
  objects, no SQL/DB driver types. Depends on repository *interfaces*, not
  concrete implementations, so it's unit-testable without a real DB.
- **Repository layer**: All DB/external-API interaction lives here, behind an
  interface defined by (and owned by) the service layer that consumes it.

Include one trivial example resource (a `widgets` resource, with list, get,
and create) threaded through all three layers so the pattern is concrete,
not just described in a README.

### The operation registry

Each service-layer operation is declared once in a small registry: name,
summary, input type, output type, handler. Everything downstream *reads* the
registry rather than restating it:

- HTTP routes and their request/response binding
- `/openapi.json`
- `/llms.txt`

```go
// internal/service/registry.go  (Go — explicit registration)
ops.Register(ops.Op{
    Name:    "widgets.get",
    Summary: "Fetch a widget by ID.",
    Method:  http.MethodGet, Path: "/widgets/{id}",
    In:      GetWidgetInput{}, Out: Widget{},
    Handler: svc.GetWidget,
})
```

```python
# src/<pkg>/internal/service/widgets.py  (Python — decorator over the same shape)
@ops.register(name="widgets.get", method="GET", path="/widgets/{id}")
async def get_widget(self, inp: GetWidgetInput) -> Widget:
    """Fetch a widget by ID."""
```

**Why this is worth the ceremony**, now that there's only one transport:
Go has no framework that generates an OpenAPI spec, so *something* has to be
the source of truth for it, and the realistic options are a hand-maintained
spec (drifts immediately), annotation comments scraped by a codegen tool
(another toolchain, and still a second authoring location), or a registry
the router itself consumes. Only the third makes the spec structurally
incapable of disagreeing with the routes. It also happens to be the seam
that makes adding a second transport later — MCP, gRPC, a CLI — an addition
rather than a rewrite. Adding an operation must be a single edit; if a
developer can add an HTTP route without it appearing in OpenAPI and
`llms.txt`, the design has failed and should be fixed rather than documented
around.

Add a test that walks the registry and asserts every operation is routable
and appears in both generated artifacts.

### Error contract

The service layer must be able to say "not found" / "invalid" / "conflict" /
"internal" without importing any transport type. Define:

- A domain error taxonomy in the service layer — sentinel errors in Go, an
  exception hierarchy in Python — with **identical categories** in both
  languages, listed in `docs/architecture.md`.
- A mapping owned by the transport: domain category → HTTP status. One
  table, documented once, so a second transport later adds a column rather
  than inventing its own scheme.
- An identical wire error body in both languages. Use RFC 9457
  `application/problem+json`: `type`, `title`, `status`, `detail`,
  `instance`, plus a `trace_id` extension member so a user-reported error
  maps directly to a trace.
- A hard rule, stated in AGENTS.md: driver errors and stack traces never
  cross the transport boundary. Log the detail, return the category.

`internal/apierror/` owns the taxonomy and the mapping table.

### Middleware order

With recovery, tracing, metrics, logging, request-ID, and timeout all in
play, order matters and must be identical in both languages. Specify the
canonical chain once in `docs/architecture.md` and match it — outermost
first:

```
recovery → request-id → tracing → metrics → [auth: reserved] → logging → timeout → handler
```

Recovery outermost so a panic in any other middleware is still caught;
tracing outside metrics and logging so both can attach the trace ID. The
`auth` slot is named but empty in Phase 1 — see the deferral table and its
ADR. Naming it now means adding auth later doesn't change the chain that
`make parity` validates.

---

## Language-specific stack

**Go**
- Latest stable Go version, **pinned explicitly** (see "Version pinning")
- `net/http` (stdlib) — no web framework
- `log/slog` (stdlib) for logging
- Lint/format: `golangci-lint` + `gofumpt`, config checked in

**Python**
- Latest stable CPython that all listed dependencies support
- `uv` for package/dependency management (`pyproject.toml`, `uv.lock`)
- FastAPI for the web framework
- Lint/format: `ruff` (both roles), plus `mypy --strict` for type checking

Both: asdf-managed via `.tool-versions`, with `uv` handling the
virtualenv/deps inside the pinned Python version.

Note the asymmetry: Go type-checks as part of compilation, Python doesn't. If
`make lint` runs `golangci-lint` on one side and only `ruff` on the other,
the targets aren't actually equivalent — hence mypy in Python's `lint`.
Both languages' lint tooling is pinned to an exact version.

Keep dependency lists minimal and justify each one in the generated README.

### Version pinning

"Latest stable" means **latest stable at template-authoring time, pinned into
the template** — not resolved dynamically during `copier copy`. Two
developers minting a week apart must get byte-identical toolchains, or the
mint mark stops identifying a build.

Pin exact versions in `.tool-versions`, `go.mod`, and
`pyproject.toml`/`uv.lock`. Bumping a version is a change to the mint repo
that bumps the template version and reaches existing services via
`copier update`.

---

## Configuration

Precedence, highest to lowest: **environment variables > YAML file**.

There is deliberately no third source. An earlier draft allowed JSON "where
there's a concrete reason"; there isn't one, and an unused code path in a
template is worse than no path — every generated service inherits its
maintenance and documentation cost forever. Note in `docs/config.md` that a
third source can be added in exactly one place if a concrete need appears.

- Config loading is centralized in `internal/config` — nothing else in the
  service reads env vars or files directly. Enforce this in `make lint`
  (a grep-level check is fine) and state it in AGENTS.md.
- Provide a single typed config struct/model (Go: plain struct; Python:
  pydantic `BaseSettings`) with sane defaults, so a service runs locally
  with zero configuration.
- Document the exact env var naming convention (propose one — e.g.
  `MINT_<SECTION>_<KEY>`) and make it identical in spirit between Go and
  Python, adjusting only for language casing conventions.
- Define the canonical `ENV` values once: `local | dev | staging | prod`.
  Anything else is a startup error.
- **Validate at startup and report every invalid field at once**, not just
  the first. Pydantic does this natively; Go needs deliberate effort to
  match it. The behavior must be identical, and there must be a test that
  feeds three bad values and asserts three errors in the output.
- **Ship a `--print-config` flag and a `make config` target** that dump the
  effective resolved configuration with secrets masked, annotating each key
  with which source won. This is the fastest way for a human *or* an agent
  to debug precedence, and it makes the service self-describing in the same
  spirit as `/llms.txt`.
- **Secrets**: never in `config.yaml` or `config.local.yaml`; environment
  variables only in Phase 1. Mark secret fields in the config type so
  `--print-config` and any log line masks them automatically. Document that
  the seam for a real secrets provider lives in `internal/config` and
  nowhere else.
- Write `docs/config.md` as the single source of truth for this scheme, and
  have each generated service's README link to it.

---

## Logging — two-tier system

Every log line, in both tiers, carries at minimum:

1. `timestamp`
2. `level`
3. `service` (service name from config)
4. `service_version`
5. `env`
6. `trace_id` (omitted entirely if no active trace — never fabricate one)
7. `span_id` (same rule)

**Tier 1 — local development**: human-readable, colorized console output.
Controlled by an env var (`LOG_FORMAT=console`, the default when
`ENV=local` or unset).

**Tier 2 — remote**: structured JSON, one object per line, stable field
names, safe for log aggregators. Used whenever `LOG_FORMAT=json` or in any
non-local environment.

- Go: build this on `log/slog` — `slog.NewTextHandler` for tier 1,
  `slog.NewJSONHandler` for tier 2, selected at startup by config.
- Python: pick one library that cleanly supports both a human console
  renderer and a JSON renderer from the same call sites (e.g. `structlog`),
  rather than hand-rolling formatters. Justify the choice in the README.
- The trace and span IDs must be pulled from the active OpenTelemetry span
  context automatically — callers never pass them manually.
- **Reserved vs. free-form keys**: the seven fields above are reserved and
  may not be overridden by call sites. Everything else is free-form, in
  `snake_case`, documented in `docs/logging.md`.
- **Redaction**: a documented list of key names (`password`, `token`,
  `secret`, `authorization`, `api_key`, …) is redacted by the handler
  itself, not by discipline at call sites. Secrets never reach a log
  regardless of what a caller does. Test this.
- Document the exact field set and naming in `docs/logging.md` as the source
  of truth; both languages must match it exactly, and `make parity` checks
  emitted keys against that document.

---

## Tracing

Use **OpenTelemetry** (not the deprecated OpenTracing project).

- **Default exporter when `ENV=local` and no OTLP endpoint is configured: a
  no-op (or stdout, behind a flag) exporter.** A fresh `make run` must not
  spew connection-refused retries at a Jaeger that isn't running — that's a
  terrible first impression for a template whose whole pitch is that it just
  works. Configuring an endpoint is what opts you into real export.
- When an endpoint *is* configured, export **direct to Jaeger** via OTLP (no
  collector in this phase), endpoint configurable through the standard config
  system, `localhost:4317` being the conventional local value.
- Document how to get a local Jaeger running in the generated README — a
  single `docker run` line is fine and doesn't violate the phase boundary;
  it's a doc, not a compose file we maintain.
- Auto-instrument the transport layer so every inbound request starts/joins a
  trace span with no per-handler boilerplate.
- Propagate trace context through the service and repository layers (pass
  `context.Context` in Go; the equivalent context propagation in
  Python/FastAPI).
- **Flush the tracer provider on shutdown.** Spans from the final requests
  are silently lost otherwise; this is the single most common OTel bug and
  the smoke test should catch it.
- The generated README notes that swapping the exporter for an OTel Collector
  later is a config change, not a code change — keep the exporter wiring
  isolated in `internal/observability` for that reason.

---

## Metrics

Use **Prometheus** client libraries (`client_golang` for Go,
`prometheus_client` or `prometheus-fastapi-instrumentator` for Python).

- Expose `/metrics` on the admin port.
- Ship with request count, request duration histogram, and in-flight
  requests as default instrumentation on every route, with no per-handler
  code required.
- Naming convention for custom metrics should be documented and consistent
  between languages (propose one — e.g. `<service>_<noun>_<unit>_<suffix>`
  per Prometheus conventions).
- **Cardinality guardrail**, documented in AGENTS.md and enforced by the
  default instrumentation: never label with unbounded values. Route labels
  use the registered template (`/widgets/{id}`), never the concrete path
  (`/widgets/123`). One sentence here prevents an expensive incident later.

---

## Health endpoints

Provide, identically named across both languages, on the admin port:
- `GET /healthz` — liveness. Process is up. Touches no dependencies, ever.
- `GET /readyz` — readiness. Runs registered dependency checks.

Keep these in the transport layer, calling into a small health-check
mechanism that repository implementations register against (so adding a DB
later means registering a ready-check, not touching the endpoint). Each
registered check has its own timeout and is marked required or optional;
`/readyz` fails only on required checks, and its response body lists every
check with its status either way.

---

## Runtime lifecycle

Identical behavior in both languages, and covered by the smoke test:

- **Graceful shutdown** on SIGTERM/SIGINT: stop accepting new connections,
  drain in-flight requests up to a configurable timeout, then flush the
  tracer provider and close the logger. Exit non-zero if the drain times
  out.
- **Panic / unhandled-exception recovery** as the outermost middleware: log
  at error with the trace ID and stack, return the documented
  `problem+json` 500. An unrecovered panic must not take the process down.
- **Server timeouts**: read-header, read, write, and idle timeouts all set
  from config, with sane non-zero defaults. Go's `http.Server` with a zero
  `ReadHeaderTimeout` is both a golangci-lint failure and a slowloris
  vector — don't ship it.
- **Per-request context deadline** derived from config, propagated to the
  service and repository layers so a slow dependency can't pin a request
  open forever.
- **Startup ordering**: config → logging → tracing/metrics → repositories →
  health registration → listeners. Fail fast and loudly at any step, with
  the failure logged in the configured format.

---

## Testing

The tests that ship in the template *are* the pattern every future service
copies, so they carry as much weight as the application code. Write
`docs/testing.md` as the source of truth for these conventions.

Every generated service ships with:

- **A fake in-memory repository implementation** — this is the payoff of the
  interface rule, so demonstrate it rather than describing it. Service-layer
  tests use it and require no database.
- **One test per layer for the example resource**: service (business logic
  and error categories) and transport (routing, binding, status and
  `problem+json` mapping).
- **A registry-coverage test**: every registered operation is routable and
  appears in `/openapi.json` and `/llms.txt`.
- **Config tests**: precedence (env beats YAML), multi-error validation,
  secret masking in `--print-config`.
- **A logging test**: asserts the reserved field set is present and that
  redacted keys never appear in output.

Conventions: table-driven tests in Go, parametrized `pytest` in Python;
identical test names for equivalent cases so the parity check can diff them.
Integration tests that need external dependencies are tagged (`//go:build
integration`, `@pytest.mark.integration`) and excluded from `make test` by
default, with `make test-integration` running them.

`make test` prints coverage in both languages, in the same format. No hard
coverage gate in Phase 1 — a threshold on generated stub code creates
busywork rather than confidence. Revisit when there are real services.

---

## AI-agent discoverability

These services should be as easy for an AI agent to understand and drive as
for a human. Everything in this section derives from the operation registry
and the `docs/` tree — nothing here is hand-authored twice.

**AGENTS.md** — at the root of both the template repo and every generated
service, with `CLAUDE.md` as a symlink to it so Claude Code picks it up
without a second file to keep in sync. For a generated service it should
give a coding agent what it needs without re-deriving it file by file: the
three-layer architecture and its rules, the operation registry and how to
add an operation, where the example resource lives, the error taxonomy, and
explicit "don't do this" boundaries (the service layer never imports
`net/http` or FastAPI request types; nothing outside `internal/config` reads
an env var; never label a metric with an unbounded value).

For commands, AGENTS.md contains a **generated block** — delimited by
markers, written by `make agents-docs` from the Makefile's own `##`
comments, and checked for staleness by the same target. That way the
commands are neither restated by hand (drift) nor merely linked (useless to
an agent that then has to go read a Makefile).

`docs/agents.md` in the template repo is the source of truth for what an
AGENTS.md must contain; both language templates render from it.

**Static discovery** — served by the HTTP transport, generated from the
registry:
- `GET /openapi.json` — from the registry in both languages. FastAPI gives
  Python most of this for free; Go reflects over the registry.
- `GET /llms.txt` — a short generated index pointing at the OpenAPI spec, the
  `docs/` files, and the example resource, built the same way in both
  languages.

---

## Makefile parity

This is a hard requirement: **the Makefile target names, behavior, and
output should be indistinguishable between a Go service and a Python
service.** Someone should be able to `cd` into either kind of generated
service and run the same commands without checking which language it is.

Both Makefiles need identical targets for:

| target | behavior |
| --- | --- |
| `run` | boots the service with local config |
| `build` | produces the runnable artifact |
| `test` | unit tests + coverage summary |
| `test-integration` | the tagged/marked tests |
| `lint` | linter + type check + the "no env vars outside config" check |
| `fmt` | formats in place |
| `config` | prints effective config, secrets masked |
| `agents-docs` | regenerates `/openapi.json`, `/llms.txt`, and AGENTS.md's generated block from source; exits non-zero if committed output is stale |
| `clean` | removes build artifacts |
| `help` | self-documents targets by parsing `##` comments |

Implementation underneath each target will obviously differ (`go build` vs
whatever `uv` needs), but target names, argument shapes, exit codes, and
console output style must match. The parity check diffs the target lists —
don't rely on remembering to.

---

## Parity enforcement

`make parity` at the mint repo root, exiting non-zero on any drift:

1. Diff the two `copier.yml` question sets — names, order, types, defaults,
   help strings.
2. Generate both templates from an identical fixture answers file into a
   temp dir.
3. Diff the generated directory trees, normalized (extensions stripped,
   `src/<pkg>/` prefix stripped from the Python side).
4. Diff `make help` output from both — target names and descriptions.
5. Boot both and diff the emitted log keys against the table in
   `docs/logging.md`.
6. Diff the operation lists from both services' `/openapi.json`.
7. Diff the middleware chain order reported by each service against
   `docs/architecture.md`.
8. Diff the test case names for the shared conventions in `docs/testing.md`.

`make verify` runs `scripts/verify-template.sh`: generate both into a temp
dir, build, boot, exercise `/healthz`, `/readyz`, `/metrics`, the widgets
endpoints, `/llms.txt`, `/openapi.json`, assert a log line appears in each
tier and a span is exported, send SIGTERM and assert clean drain — then tear
down. Assertions, not eyeballing.

These two targets are the deliverable that keeps every other guarantee in
this spec true over time. Treat them as first-class code, not scripts. Each
implementation chunk in `tasks/` adds its own checks to them as it lands,
rather than deferring all of it to the end.

---

## asdf + direnv

- `.tool-versions` in each generated service pins the exact language version.
- `.envrc` uses direnv to: pick up asdf-managed versions automatically, load
  `config/config.local.yaml` overrides if present, and (Python only) activate
  the `uv`-managed environment. Should work with a single `direnv allow` and
  no other manual setup.
- Document the one-time developer machine setup (installing asdf and direnv
  themselves) once in the top-level `mint/README.md`, not repeated
  per-language.

---

## Decisions

Every item in "Things to flag back to me" — and any other non-obvious call
made while building — gets a short ADR in `docs/decisions/`, numbered,
with context / decision / consequences. Chat scrollback is not a durable
record, and an agent opening this repo in six months should be able to find
out *why* the env var prefix is what it is without asking anyone.

---

## Things to flag back to me rather than silently deciding

- **Whether Go reflection over the operation registry produces an OpenAPI
  spec good enough to hand to a client generator.** If it doesn't, the
  registry's shape changes and it's upstream of every layer — so settle this
  before building on it.
- The exact env var naming scheme and metric naming scheme — propose one,
  but treat it as a proposal, since every future service inherits it.
- Any place where Go and Python idioms genuinely can't be made to match
  (e.g. if a "matching" Makefile target would force something unnatural in
  one language) — tell me the tradeoff instead of picking one silently.
- Any additional dependency beyond what's listed above — justify it before
  adding it.
- Whether generated `llms.txt` / OpenAPI output should be committed to the
  repo (so drift shows up as a PR diff) or produced purely at build time
  into a gitignored artifact.
- Whether the split `port` / `admin_port` default is right, or whether a
  single listener is the better default for how these will actually be
  deployed.
- Whether per-template versioning (`go-service/v1.2.0`) causes friction with
  `copier update` in practice, and whether `templates/_common/` changes
  should bump both.
