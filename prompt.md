# Mint — Microservice Template Generator (Go + Python)

> This file is the **specification**. It is the durable statement of what
> Mint must be, and it does not get handed to an agent in one piece.
> Implementation is broken into ordered chunks in `tasks/` — each one
> references the sections here that it implements.
>
> **Every decision below marked with an ADR reference was settled by an
> executed spike, not by reasoning.** Where this document and an ADR
> disagree, the ADR wins and this document is stale — say so rather than
> splitting the difference.

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

Chunk 01 sharpened the second principle into a rule worth stating outright:
**three of the five things this spec originally got wrong failed *silently*.**
Pure reflection emitted an OpenAPI document that lied and still passed its
validator; slash-tagged templates produced a correct-looking mint mark while
`copier update` tracked HEAD; `pydantic_settings` let a `.env` file beat YAML
without complaint. Prefer a check that fails loudly over a design that
appears to work.

## Scope

**Phase 1 (this spec)**: app code, config, logging, errors, HTTP transport,
health checks, lifecycle, tracing, metrics, generated discovery docs, tests,
Makefile, asdf, direnv.

**Explicitly deferred** — do not build these, but do not preclude them:

| deferred | why | the seam |
| --- | --- | --- |
| Dockerfiles, docker-compose | Phase 2 | empty `docker/` dir, reserved |
| CI pipelines | Phase 2 | empty `.github/workflows/`, reserved |
| Kubernetes manifests | Phase 3 | `service_name` is DNS-label-safe; `service_owner` captured now |
| **MCP server** | SDK churn — Python shipped a breaking v2.0.0 in July 2026 that would owe every generated service a migration ([ADR 0004](docs/decisions/0004-defer-the-mcp-server.md)) | registry is transport-agnostic; a spike built a working MCP transport in 62 lines with zero edits to the service or error layers |
| **Authentication** | expected at a gateway or mesh ([ADR 0005](docs/decisions/0005-defer-authentication-to-a-gateway.md)) | a named, empty slot in the middleware chain |

**The MCP seam is thinner than it looks, in one specific way.** The entire
middleware chain is typed `func(http.Handler) http.Handler` and lives inside
`internal/transport/http`, so a future stdio transport inherits none of it,
and the frozen chain plus its parity check would need rework. `Op` will also
likely gain an exposure field. Neither is a reason to build MCP now; both are
reasons not to claim the seam is free.

---

## Repo layout (the template source repo itself)

```
mint/
├── copier.yml               # THE single template definition — must be at the repo root
├── questions-shared.yml     # the language-agnostic question set, !include-ed
├── templates/
│   ├── _common/             # language-agnostic files, reached by relative symlink
│   │   └── docs/
│   ├── go-service/template/         # [[ ]]-parameterized Go source tree
│   │   └── docs -> ../../_common/docs
│   └── python-service/template/     # ...and Python
│       └── docs -> ../../_common/docs
├── docs/
│   ├── architecture.md      # 3 layers, registry, error contract, middleware, lifecycle
│   ├── logging.md           # the shared log schema (source of truth)
│   ├── config.md            # config precedence rules (source of truth)
│   ├── agents.md            # source of truth for AGENTS.md / discovery scheme
│   ├── testing.md           # the shared testing conventions (source of truth)
│   └── decisions/           # ADRs — the authority for everything they cover
├── tasks/                   # ordered implementation chunks
├── scripts/
│   ├── parity.sh            # the drift check
│   └── verify-template.sh   # generate → build → boot → assert → tear down
├── Makefile                 # mint's own targets
├── AGENTS.md                # context for coding agents maintaining THIS repo
├── CLAUDE.md                # symlink to AGENTS.md
├── CHANGELOG.md
└── README.md
```

**`copier.yml` must live at the repo root, and there is exactly one of it.**
This is not a style preference. Copier treats a path as VCS-tracked only when
it *is* the git repo root, so a per-template `copier.yml` under
`templates/go-service/` yields `Copying from template version None`, records
no `_commit`, and makes `copier update` exit 1 with "cannot obtain old
template references" ([ADR 0009](docs/decisions/0009-repo-wide-semver-tags.md),
Finding 4). Two separate question sets are not achievable; one shared set is
what the tool supports.

`templates/_common/` reaches both templates through a **relative symlink**.
Copier's `preserve_symlinks` defaults to false, so the content lands in the
generated service as a real file, not a dangling link — verified.

---

## Copier mechanics

### The single root `copier.yml`

Multi-document YAML with a rendered `_subdirectory` and a document-level
`!include`. Both verified working:

```yaml
---
_subdirectory: "templates/[[ language ]]-service/template"
_min_copier_version: "9.17.0"
language: {type: str, choices: {Go: go, Python: python}, default: go}
---
!include "questions-shared.yml"
---
module_path:
  when: "[[ language == 'go' ]]"
package_name:
  when: "[[ language == 'python' ]]"
```

`!include` must be its own YAML document — used as a mapping entry it fails
with `InvalidConfigFileError`.

### Questions

| question | type | notes |
| --- | --- | --- |
| `language` | choice | `go` \| `python`. Drives `_subdirectory`. |
| `service_name` | str | kebab-case, DNS-label-safe. Reject anything not matching `^[a-z][a-z0-9-]{1,38}[a-z0-9]$`. |
| `service_description` | str | one line; README and OpenAPI `info.description` |
| `service_owner` | str | team name — AGENTS.md, `target_info`, and Phase 2/3's CODEOWNERS |
| `repo_url` | str | e.g. `github.com/<org>/<service_name>` |
| `module_path` | str | Go only (`when:`-gated). Defaults to `[[ repo_url ]]`. |
| `package_name` | str | Python only (`when:`-gated). Defaults to `service_name` with `-`→`_`. |
| `port` | int | 1024–65535 |
| `admin_port` | int | `/metrics`, `/healthz`, `/readyz`. Defaults to `port + 1000`. |

Every question needs a `help` string, a validator where a bad answer would
produce code that doesn't compile, and a default where derivable.

**Jinja delimiters are `[[ ]]` / `[% %]` / `[# #]`.** Phase 2 brings GitHub
Actions and its `${{ }}` would collide.

**`_tasks`**: `git init`, then `go mod tidy` / `uv sync`, then a printed
next-steps block ending with `direnv allow` and `make run`.

### Versioning — plain repo-wide semver

Tag the repo `v1.2.0` — **not** `go-service/v1.2.0`.

Copier filters git tags through `packaging.version.parse`, so a slash tag is
discarded — and it fails *silently*: `_commit` still resolves via
`git describe`, so the mint mark renders correctly while `copier update`
quietly begins tracking HEAD. A spike watched an untagged WIP commit land in a
generated service with `check-update` reporting "up-to-date" indefinitely. No
tag scheme fixes this; PEP 440 local versions parse but Copier takes the
global max, resolving a Go service to `v1.1.0+python`
([ADR 0009](docs/decisions/0009-repo-wide-semver-tags.md)).

The measured cost of a Python-only release on a Go service is two lines
(`_commit` and the mint mark), zero code churn, zero conflict risk. Scope
lives in `CHANGELOG.md` as `go-service:` / `python-service:` / `common:`
entries, not in tag names. A `templates/_common/` change bumps the single
version and reaches both languages by construction.

### Updates

`copier update` is the reason to use Copier over cookiecutter. Document it in
the README from an observed run. Use `_migrations` for changes that can't
merge cleanly. Where a generated file is meant to be owned by the service
afterward, say so in a comment at its top.

### Mint mark

Each generated README surfaces its origin from `.copier-answers.yml`'s
`_commit` — never a hand-written note. Degrade gracefully (omit the line
entirely) when the template repo has no tags.

---

## Generated service layout

Directory names and purposes are identical across languages; Python nests the
same tree under `src/<package_name>/`.

```
<service-name>/
├── cmd/<service-name>/main.go   |  src/<pkg>/__main__.py   # composition root only
├── internal/transport/http/     |  src/<pkg>/internal/transport/http/
├── internal/service/            |  src/<pkg>/internal/service/
├── internal/repository/         |  src/<pkg>/internal/repository/
├── internal/config/             |  src/<pkg>/internal/config/
├── internal/logging/            |  src/<pkg>/internal/logging/
├── internal/observability/      |  src/<pkg>/internal/observability/
├── internal/apierror/           |  src/<pkg>/internal/apierror/
├── config/
│   ├── config.yaml                 # defaults, checked in
│   └── config.local.yaml.example   # committed; config.local.yaml gitignored
├── docs/                           # symlinked from templates/_common/docs/
├── openapi.json                    # generated, COMMITTED (ADR 0007)
├── llms.txt                        # generated, COMMITTED (ADR 0007)
├── .gitattributes                  # openapi.json -merge
├── AGENTS.md
├── CLAUDE.md                       # symlink to AGENTS.md
├── .gitignore
├── .tool-versions
├── .envrc
├── Makefile
└── README.md
```

`internal/transport/http/` nests deliberately — one transport today, and the
nesting is what makes a second an addition rather than a refactor.

---

## Architecture rules

- **Transport layer**: HTTP handlers only. Parse, validate shape (not
  business rules), call the service layer, serialize. No business logic, no
  repository calls.
- **Service layer**: All business logic and validation. Plain
  language-native types in and out — no `http.Request`, no FastAPI request
  objects, no DB driver types. Depends on repository *interfaces* it owns.
- **Repository layer**: All DB/external-API interaction, behind that
  interface.

Include one example resource (`widgets`: list, get, create) threaded through
all three layers.

### The operation registry

Each operation is declared once. The router, `/openapi.json`, and `/llms.txt`
all read the registry rather than restating it.

**Reflection carries structure; it cannot carry intent.** Pure reflection was
tried and produced a document that *lied while passing its validator* —
`time.Time` became `{"type":"object","properties":{}}` and every enum
degraded to plain `string`. Four kinds of intent must be declared, and one is
harvested from source ([ADR 0001](docs/decisions/0001-generate-openapi-from-the-operation-registry.md)):

| reflection cannot infer | how it's supplied |
| --- | --- |
| path vs query vs header vs body | `path:` / `query:` / `header:` / `json:` struct tags |
| members of a named enum type | an `EnumValues() []any` method |
| min / max / pattern / format | `validate:` tags, go-playground syntax |
| `time.Time` and friends | a special-case table in the generator |
| field descriptions | a build-time `go/ast` pass in `make agents-docs` |

```go
ops.Register(ops.Op{
    Name:    "widgets.get",
    Summary: "Fetch a widget by ID.",
    Method:  http.MethodGet, Path: "/widgets/{id}",
    In:      GetWidgetInput{}, Out: Widget{},
    Errors:  []ops.Category{ops.CatNotFound, ops.CatInvalid},
    Handler: svc.GetWidget,
    // Status int — optional; defaults to 200, or 201 for POST
})

type GetWidgetInput struct {
    // ID is the widget identifier.        <- becomes the description
    ID string `path:"id" validate:"min=1,max=64"`
}
```

`Errors` and `Status` are additions to the shape this spec originally
sketched. Without `Errors`, every operation advertises an identical error set
and `widgets.get` cannot declare its 404.

**Required vs optional** is `pointer OR json ",omitempty" ⇒ optional`,
overridable with `openapi:"required"` / `openapi:"optional"`. Go cannot
distinguish absent from zero without a pointer; a PATCH field that must
accept an explicit zero has to be a pointer. That is a documented rule, not a
problem to solve.

**Python is driven from the same registry**, but not for free. FastAPI
derives placement from the *endpoint signature*, so a registry handler
`f(inp: GetWidgetInput)` makes it treat the whole model as a body and leave
`{id}` unbound — roughly 150 lines of signature synthesis fixes it. With
that, Python has one authoring location. The decorator runs at
class-definition time, so the registry holds unbound functions and the
composition root calls `registry.bind(svc)`; Go binds at registration. This
asymmetry is inherent — document it rather than engineering it away.

**Routes must be registered in specificity order.** Go's `ServeMux` picks the
most specific match; Starlette matches in registration order. Identical
registry content routed differently until the registry sorted — `/widgets/{id}`
was swallowing `/widgets/search`.

**Three checks run in `make agents-docs` and as a test**, each exiting
non-zero: structural (path template and `path:` tags agree, every input field
has a placement tag, no body on GET/DELETE/HEAD, names unique); optional
fields whose `validate` tag doesn't begin with `omitempty` (the published
schema and the runtime check would disagree); and schema validation of the
emitted document.

### Error contract

- Domain taxonomy in the service layer — sentinel errors in Go, an exception
  hierarchy in Python — with identical categories: `invalid`, `not_found`,
  `conflict`, `unauthorized`, `forbidden`, `internal`.
- A mapping table owned by the transport: category → HTTP status.
- **RFC 9457 `application/problem+json`**: `type`, `title`, `status`,
  `detail`, `instance`, plus a `trace_id` extension member.
- **FastAPI's automatic 422 breaks this contract** and must be remapped to
  400 `problem+json` via a `RequestValidationError` handler. After that the
  Go and Python operation lists diff clean.
- Driver errors and stack traces never cross the transport boundary. Log the
  detail, return the category.

### Middleware order

Outermost first, identical in both languages, frozen and parity-checked:

```
recovery → request-id → tracing → metrics → logging → [auth: reserved] → timeout → handler
```

Auth sits **inside** logging and metrics, under the rule *observe
everything, then authorize, then execute*
([ADR 0005](docs/decisions/0005-defer-authentication-to-a-gateway.md)). An
access log that omits rejected requests is a success log — you can't answer
"401s are spiking, from where?" The accepted cost: an unauthenticated flood
drives log volume directly. Auth stays outside `timeout`, because the request
deadline is the handler's budget.

A WARN at startup when `ENV != local` and no auth is registered keeps the
deferral mechanical rather than remembered.

---

## Language-specific stack

**Go**
- Go **1.26.6** ([ADR 0011](docs/decisions/0011-pinned-toolchain-versions.md))
- `net/http` (stdlib) — no web framework
- `log/slog` (stdlib), with `lmittmann/tint` for tier-1 color (see Logging)
- `go-playground/validator` for runtime constraint enforcement
- `golangci-lint` + `gofumpt`, config checked in

**Python**
- CPython **3.14.7**; FastAPI, pydantic, OTel SDK and structlog all verified
  running on it
- `uv` for dependencies (`pyproject.toml`, `uv.lock`)
- FastAPI + `structlog` ([ADR 0010](docs/decisions/0010-use-structlog-for-python-logging.md))
- `ruff` (lint + format) and `mypy --strict`

**`ruff` 0.16.0 changed its defaults from 59 rules to 413.** The template
must check in an explicit `select` rather than inherit defaults, or a ruff
upgrade silently changes what `make lint` means.

Go type-checks as part of compilation and Python doesn't — hence mypy in
Python's `lint`, or the targets aren't equivalent. Pin every tool version.

**"Latest stable" means latest stable at template-authoring time, pinned into
the template** — never resolved during `copier copy`. Two developers minting a
week apart must get identical toolchains.

---

## Configuration

Precedence, highest to lowest: **environment variables > YAML**. There is
deliberately no third source.

**Env var naming** ([ADR 0002](docs/decisions/0002-environment-variable-naming.md)):
`MINT_` + the config path upper-cased, with `__` between levels and the key's
own underscores preserved.

```
server.read_timeout                     → MINT_SERVER__READ_TIMEOUT
observability.tracing.otlp_endpoint     → MINT_OBSERVABILITY__TRACING__OTLP_ENDPOINT
```

Single-underscore nesting was proven **non-injective** — `server.read_timeout`
and `server.read.timeout` collide silently. A constant `MINT_` prefix beats a
service-name prefix on a hard fact: Kubernetes injects `{SVCNAME}_PORT` by
default, so `WIDGET_SVC_PORT` would arrive as `tcp://10.0.162.149:8080`.

**This supersedes this document's own earlier prose.** There is no bare `ENV`
or `LOG_FORMAT`; they are `MINT_ENV` and `MINT_LOGGING__FORMAT`, with no
aliases.

**OpenTelemetry**: Mint defers on *transport* (`OTEL_EXPORTER_OTLP_*` read as
an explicitly enumerated fallback **inside** `internal/config`, so the lint
rule and `--print-config` still hold) and owns *identity*
(`OTEL_SERVICE_NAME` and `OTEL_RESOURCE_ATTRIBUTES` ignored). Logs and spans
disagreeing about `service` or `env` would break the error→trace path.

**`pydantic_settings` defaults to a four-source chain** and silently let a
`.env` file beat YAML in the spike. The Python template must override
`settings_customise_sources`, and a parity check must assert both languages
report exactly `["yaml", "env"]`
([ADR 0006](docs/decisions/0006-load-config-from-env-over-yaml-only.md)).
`.env` is **direnv's** business (`dotenv_if_exists` in `.envrc`), never the
application's.

Also required:
- Config loading centralized in `internal/config`; nothing else reads an env
  var or file. Enforced by a grep check in `make lint`.
- One typed config object with defaults sane enough to boot with zero
  configuration.
- `ENV` values are `local | dev | staging | prod`; anything else is a startup
  error.
- **Validation reports every invalid field at once.** Pydantic does this
  natively; Go needs deliberate effort to match.
- `--print-config` and `make config` dump the effective config with secrets
  masked, annotating which source won.
- Secrets are env-only, marked in the type so masking is a property of the
  type rather than call-site discipline.

---

## Logging — two tiers

Every line carries: `timestamp`, `level`, `service`, `service_version`,
`env`, `trace_id`, `span_id`. Trace and span IDs come from the active OTel
span context automatically and are **omitted entirely** when there is no
span — never empty, never fabricated.

**Tier 1 — console**, colorized, default when `ENV=local`. Go uses
`lmittmann/tint`; `slog.NewTextHandler` emits no ANSI color at all, so this
document's original claim was unachievable as written. Python uses
structlog's `ConsoleRenderer`.

**Tier 2 — JSON**, one object per line. Go's `JSONHandler` wrapped in a
custom handler; structlog's `JSONRenderer` in Python. **Proven
byte-identical** across languages, given `separators=(",", ":")` and
`ensure_ascii=False` to match Go's `encoding/json`.

Forced consequences of that parity, all documented in `docs/logging.md`:
Python levels normalize to slog's vocabulary (`warning`→`warn`,
`critical`→`error`); nested dict keys must be explicitly sorted in Python
because Go's `encoding/json` sorts map keys; **`make parity` asserts tier 2
byte-for-byte and tier 1 on key names only**, since tint and
`ConsoleRenderer` will never agree glyph-for-glyph.

**Redaction happens in the handler**, not at call sites: a documented key
list, applied to nested and list-embedded values, in both tiers.

**Reserved keys cannot be overridden** by call sites. Free-form keys are
`snake_case`.

**uvicorn**: suppress, don't reconfigure. Boot from `__main__.py` with
`uvicorn.run(app, log_config=None, access_log=False)`; the middleware emits
the structured access line. The `uvicorn` CLI does **not** work — it calls
`configure_logging()` before importing the app — so **`make run` uses
`python -m <pkg>`**.

---

## Tracing

OpenTelemetry, wired only in `internal/observability`.

- **When `ENV=local` and no OTLP endpoint is configured, install a no-op
  exporter.** A fresh `make run` must not emit a single connection-refused
  retry.
- With an endpoint configured, export OTLP direct to Jaeger.
- Auto-instrument the transport; span names use the route template.
- Propagate context through service and repository layers.
- **Flush the tracer provider on shutdown**, and assert it in the verify
  script — final-request spans are silently lost otherwise.

---

## Metrics

Names and labels ([ADR 0003](docs/decisions/0003-metric-naming-and-labels.md)):

| metric | labels |
| --- | --- |
| `http_server_requests_total` | `method`, `route`, `status` |
| `http_server_request_duration_seconds` | `method`, `route`, `status` |
| `http_server_active_requests` | `method`, `route` |

OTel's advisory buckets, declared literally in both languages. Defaults are
unprefixed; custom metrics take `<namespace>_<subsystem>_<noun>_<unit>_<suffix>`.

**`service_owner` is not a label.** It goes in
`target_info{service_name,service_version,service_owner,deployment_environment_name}`,
joinable via Prometheus 3's `info()`. A re-org would otherwise change the
identity of every series and break `rate()` across the boundary.

**Neither language's turnkey instrumentation is usable.** `promhttp` *panics*
on a `route` label and lower-cases methods; `prometheus-fastapi-instrumentator`
hardcodes `handler`/`status` and groups codes to `2xx`. Both languages get
~60 lines of hand-written middleware over the raw primitives, which do
produce byte-identical names and labels.

**Parity must compare parsed `(family, sorted label keys, type)` over a
Mint-owned allowlist, never raw text**: Python emits a `_created` gauge per
counter (suppress with `disable_created_metrics()`, not the env var — that
would violate ADR 0002), renders `le="1.0"` against Go's `le="1"`, orders
families differently, and exposes 4 default families to Go's 38.

**Phase 1 assumes a single Python worker.** `prometheus_client` multiprocess
mode makes the in-flight gauge lie without `PROMETHEUS_MULTIPROC_DIR` and
`multiprocess_mode="livesum"`.

Cardinality rule, enforced in code: route labels use the registered template,
never the concrete path.

---

## Health endpoints and ports

On the admin port:
- `GET /healthz` — liveness. Touches no dependencies, ever.
- `GET /readyz` — readiness. Runs registered checks, each with its own
  timeout and a required/optional flag. Fails only on required ones; the body
  lists every check either way.

**Ports stay split** at `port + 1000`, but the rationale is **routing and
lifecycle, not security** ([ADR 0008](docs/decisions/0008-serve-api-and-admin-on-separate-ports.md)).
Any pod reaching the pod IP reaches every container port — kubebuilder now
defaults `--metrics-bind-address` to `0` for exactly this reason. What the
split actually buys is drain visibility: mid-drain, split returns
`503 "draining"` from `/readyz` while collapsed returns connection-refused,
losing readiness detail and the final metrics scrape. Setting
`admin_port == port` collapses onto one listener and must keep working.

**Two `uvicorn.Server` instances race on signal handlers** and the process
dies exit 143 before draining. The fix is one line, and chunk 06's SIGTERM
assertion must run against the split config — the only one where the bug
appears.

---

## Runtime lifecycle

- **Graceful shutdown** on SIGTERM/SIGINT: stop accepting, drain up to a
  configurable timeout, flush the tracer provider, close the logger. Non-zero
  exit if the drain times out.
- **Panic/exception recovery** outermost: log with trace ID and stack, return
  `problem+json` 500. The process survives.
- **Server timeouts** from config with non-zero defaults — read-header, read,
  write, idle. A zero `ReadHeaderTimeout` is a lint failure and a slowloris
  vector.
- **Per-request context deadline**, propagated downward.
- **Startup ordering**: config → logging → tracing/metrics → repositories →
  health registration → listeners. Fail fast and loudly.

---

## Testing

The shipped tests are the pattern every future service copies.
`docs/testing.md` is the source of truth.

- **A fake in-memory repository** — the payoff of the interface rule.
- **One test per layer** for widgets: service (logic and error categories),
  transport (routing, binding, status, `problem+json`).
- **Registry coverage**: every operation is routable and appears in
  `openapi.json` and `llms.txt`.
- **Config**: precedence, multi-error validation, secret masking, and that
  both languages report exactly `["yaml", "env"]`.
- **Logging**: reserved fields present, redacted keys absent.

Table-driven in Go, parametrized in Python, with identical test names for
equivalent cases so parity can diff them. Integration tests are tagged and
excluded from `make test`. Starlette 1.6.0 deprecates `httpx` for **`httpx2`**
in the test client.

`make test` prints coverage in both, same format. No hard gate in Phase 1.

---

## AI-agent discoverability

**AGENTS.md** at the root of the template repo and every generated service,
with `CLAUDE.md` symlinked to it. It carries the three-layer architecture and
its rules, the registry and how to add an operation, where widgets lives, the
error taxonomy, and explicit "don't do this" boundaries. Commands live in a
**generated block** written by `make agents-docs` from the Makefile's `##`
comments — neither restated by hand nor merely linked.
`docs/agents.md` is the source of truth for its contents.

**`/openapi.json`** — OpenAPI **3.1 canonical**, served at that path, plus a
mechanically downgraded **3.0.3** copy alongside. `oapi-codegen` cannot read
3.1 at all (it rejects numeric `exclusiveMinimum`); FastAPI's own 3.1 output
fails identically, so this is an ecosystem gap, not a defect in the approach.
The downgrade is ~20 lines: rewrite `exclusiveMinimum`/`exclusiveMaximum`,
drop `jsonSchemaDialect`. Publish named types as components, never inline,
and attach descriptions to `$ref`s via `allOf` so the document downgrades
cleanly.

**`/llms.txt`** — generated, never hand-written.

**Both are committed to the generated repo**
([ADR 0007](docs/decisions/0007-commit-the-generated-discovery-artifacts.md)),
so drift shows up as a PR diff. Measured: `copier update` leaves
`openapi.json` untouched with zero conflict markers, because Copier only
three-way-merges files it renders — which makes it a **rule** that these are
never template files, not even placeholders. `.gitattributes` sets
`openapi.json -merge`; git's default text merge leaves markers that make the
JSON unparseable mid-merge.

---

## Makefile parity

**Target names, behavior, and output must be indistinguishable between a Go
service and a Python service.**

| target | behavior |
| --- | --- |
| `run` | boots the service (Python: `python -m <pkg>`, not the uvicorn CLI) |
| `build` | produces the runnable artifact |
| `test` | unit tests + coverage summary |
| `test-integration` | the tagged/marked tests |
| `lint` | linter + type check + the "no env vars outside config" check |
| `fmt` | formats in place |
| `config` | prints effective config, secrets masked |
| `agents-docs` | regenerates `openapi.json` (3.1 + 3.0.3), `llms.txt`, and AGENTS.md's generated block; runs the three registry checks; exits non-zero if committed output is stale |
| `clean` | removes build artifacts |
| `help` | self-documents by parsing `##` comments |

---

## Parity enforcement

`make parity`, exiting non-zero on drift:

1. **Assert the shared question set** — with one root `copier.yml` there is
   no second set to diff, so this becomes an assertion that every question is
   either shared or correctly `when:`-gated, and that no language-specific
   question exists without a counterpart.
2. Generate both from one fixture answers file.
3. Diff the normalized directory trees.
4. Diff `make help` output.
5. Boot both; diff tier-2 log output **byte-for-byte** and tier-1 **key names
   only**, against `docs/logging.md`.
6. Diff the operation lists from both `openapi.json` files.
7. Diff the actual middleware chain order against `docs/architecture.md`.
8. Diff parsed metric families — `(family, sorted label keys, type)` over the
   Mint-owned allowlist, never raw text.
9. Assert both config loaders report exactly `["yaml", "env"]`.
10. Diff test case names for the shared conventions.

`make verify` runs `scripts/verify-template.sh`: generate both, build, boot,
exercise `/healthz`, `/readyz`, `/metrics`, the widgets endpoints,
`/llms.txt`, `/openapi.json`; assert a log line in each tier and an exported
span; SIGTERM against the **split-port** config and assert clean drain; tear
down.

Each implementation chunk adds its own checks as it lands. **A parity check
that has never been seen to fail is not known to work** — chunk 10 proves
each one against the drift it targets.

---

## asdf + direnv

- `.tool-versions` pins the exact language version per generated service.
- `.envrc` picks up asdf versions, loads `config/config.local.yaml` if
  present, runs `dotenv_if_exists`, and (Python) activates the uv
  environment. One `direnv allow`, no other setup.
- One-time machine setup documented once in the top-level README.

---

## Decisions

`docs/decisions/` is the authority for everything it covers. Supersede
rather than edit — an ADR records what was decided *then*.

All eleven Phase 1 ADRs are **accepted**. Anything this document says that
contradicts one is stale.

## Still open

- Whether the committed-artifact decision survives contact with real review
  habits. ADR 0007 records the reversal trigger (a semantic spec-diff in CI
  plus `linguist-generated`) rather than pretending the downside is
  mitigated.
- Any Go/Python idiom mismatch discovered during implementation that can't be
  closed — report the tradeoff instead of picking silently.
- Any dependency beyond those listed above — justify before adding.
