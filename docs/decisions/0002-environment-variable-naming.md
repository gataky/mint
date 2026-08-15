# 0002 — Namespace environment variables `MINT_`, nest with `__`

**Status:** accepted (2026-08-14)
**Date:** 2026-08-14
**Chunk:** [01 — Decisions and ADRs](../../tasks/01-decisions.md)

## Context

The spec (§ Configuration) says "document the exact env var naming convention
(propose one — e.g. `MINT_<SECTION>_<KEY>`)" and explicitly treats it as a
proposal. Every service ever minted inherits the answer, and changing it later
means a `_migrations` entry plus a coordinated deploy for every service in the
fleet, so it is worth interrogating now.

`MINT_<SECTION>_<KEY>` as literally written is ambiguous, and the ambiguity is
not theoretical. The config shape chunk 03 has to build already contains
`server.read_timeout` (a two-word leaf) and `observability.tracing.otlp_endpoint`
(three levels deep). A spike that derives env names from the config struct by
reflection, run with both a single- and a double-underscore separator
(`scratchpad/adr-0002-0003/gocfg/`):

```
=== delimiter "__" (proposed) ===
  MINT_ENV                                       <- env
  MINT_OBSERVABILITY__TRACING__OTLP_ENDPOINT     <- observability.tracing.otlp_endpoint
  MINT_SERVER__ADMIN_PORT                        <- server.admin_port
  MINT_SERVER__PORT                              <- server.port
  MINT_SERVER__READ_TIMEOUT                      <- server.read_timeout
  MINT_SERVER__TIMEOUTS__IDLE                    <- server.timeouts.idle
  MINT_SERVER__TIMEOUTS__READ_HEADER             <- server.timeouts.read_header

COLLISION delim="_" MINT_SERVER_READ_TIMEOUT <- server.read_timeout AND server.read.timeout
delim="_" collisions=1
delim="__" collisions=0
```

The single-underscore form is not injective: the moment anyone adds a `read`
subsection, two distinct config keys claim one env var and the loser is decided
by struct field order. A separator that is only unambiguous until someone adds
a section is not a convention, it's a trap with a fuse.

Three other forces:

**Kubernetes already owns the service-name prefix.** The obvious alternative to
a constant prefix — deriving it from `service_name`, e.g. `WIDGET_SVC_` — is
actively dangerous. For every active Service, the kubelet injects
`{SVCNAME}_SERVICE_HOST` and `{SVCNAME}_SERVICE_PORT` plus Docker-link-compatible
variables including `{SVCNAME}_PORT` and `{SVCNAME}_PORT_8080_TCP`, with the
Service name upper-cased and dashes converted to underscores. This is on by
default (`enableServiceLinks: true`). A service named `widget-svc` would receive
`WIDGET_SVC_PORT=tcp://10.0.162.149:8080` from Kubernetes and, under a
service-name prefix scheme, that is exactly the variable Mint would parse as its
listen port. The Kubernetes docs name this failure mode themselves: the flag
exists "because possible clashing with expected program ones". Mint is
DNS-label-safe by construction (spec § Copier mechanics), which guarantees the
collision is *always* live for a service exposed by a same-named k8s Service,
not occasionally.

**OpenTelemetry SDKs read their own env vars natively, before Mint sees them.**
`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`,
`OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES` and friends are honored by the
Go and Python OTLP exporter packages with no application code. Two of those
directly overlap config Mint must own: chunk 03 puts the OTLP endpoint in the
config tree, and the spec's logging schema puts `service` and `env` on every log
line. Worse, the OTLP gRPC exporter's *default* endpoint is
`http://localhost:4317` — so constructing an exporter with no explicit endpoint
produces exactly the connection-refused retry storm that chunk 08's first
acceptance criterion forbids. The scheme has to say who wins, and the tracing
wiring has to stop deferring to SDK defaults.

**pydantic-settings expresses this natively; Go does not.** Spiked at
pydantic-settings 2.15.0 / pydantic 2.13.4
(`scratchpad/adr-0002-0003/spike_env.py`), with
`SettingsConfigDict(env_prefix="MINT_", env_nested_delimiter="__")`:

```
{ "env": "prod",
  "server": {"port": 9000, "admin_port": 9080, "read_timeout": 30.0,
             "timeouts": {"read_header": 2.5, "idle": 60.0}},
  "observability": {"tracing": {"otlp_endpoint": "localhost:4317"}} }
lowercase env accepted -> 9999
section-as-JSON -> 7777
section-as-nonJSON error: SettingsError error parsing value for field "server" from source "EnvSettingsSource"
```

Three lines of config in Python; the Go side is the ~40-line reflective walk in
the spike above. Two behaviors come along for free in Python that Go does not
have, and they are covered under Consequences.

## Decision

**Canonical form:** `MINT_` + the config key path, upper-cased, with `__`
between levels and the key's own `_` characters preserved.

```
MINT_ + UPPER( join(path_segments, "__") )
```

1. **The prefix is the constant `MINT_`.** It is not derived from
   `service_name`, and it is not a copier question. It is a single named
   constant in `internal/config` in each template (`const EnvPrefix = "MINT_"`
   / `env_prefix="MINT_"`), so an org forking Mint changes it in one place, for
   all its services at once.

2. **The level separator is `__` (two underscores). A single `_` is never a
   level separator.** A config key's own underscores are preserved verbatim, so
   `server.read_timeout` → `MINT_SERVER__READ_TIMEOUT` and `server.read.timeout`
   → `MINT_SERVER__READ__TIMEOUT`. The mapping is injective and the ambiguity in
   the spec's `MINT_<SECTION>_<KEY>` sketch is resolved by construction.

3. **Config keys are `snake_case`, must match `^[a-z][a-z0-9_]*$`, and must not
   contain `__`.** With that invariant the mapping is a bijection: every env var
   name decodes to exactly one config key. `internal/config` asserts it at
   startup over the whole config type and the parity check asserts it too, so
   the guarantee is mechanical rather than a naming guideline (spec principle 2).

4. **One canonical name per key. No aliases.** In particular this *overrides*
   the shorthand the spec's § Logging section writes informally: `ENV` becomes
   `MINT_ENV` and `LOG_FORMAT` becomes `MINT_LOGGING__FORMAT`. Bare `ENV`,
   `LOG_LEVEL`, `LOG_FORMAT` and `PORT` are read by nothing in a Mint service.
   Two names per key would mean `--print-config`'s "which source won" column has
   to explain a precedence rule *between env vars*, which is precisely the
   confusion `--print-config` exists to remove. **This needs sign-off, because
   it contradicts text in the spec.**

5. **Env vars carry scalars only.** No lists, no maps, no JSON. If a list is
   ever genuinely needed it is comma-separated with a documented parser, added
   to both languages in one change. This is a parity rule, not an aesthetic one
   — see Consequences.

6. **Case:** `UPPER_SNAKE` is the canonical and documented form. Both loaders
   match case-insensitively (Go upper-cases keys read from `os.Environ()` before
   matching; pydantic-settings does this already at its default
   `case_sensitive=False`). If two variables in the process environment
   normalize to the same canonical name, startup fails and names both.

7. **Empty string is a value, not an absence.** `MINT_SERVER__PORT=` is
   "present, empty" and fails validation for a non-string field with a message
   naming the variable. It does not silently fall through to YAML. Both
   languages behave identically; this is pydantic's natural behavior and a
   `LookupEnv`-not-`Getenv` rule in Go.

8. **Foreign env vars: defer on transport, own identity.** `internal/config`
   is still the only place in the service that reads the environment (spec
   § Configuration; enforced by the `make lint` grep), and it reads a short,
   explicitly enumerated list of variables Mint does not own:

   | concern | resolution order (highest first) |
   | --- | --- |
   | OTLP endpoint | `MINT_OBSERVABILITY__TRACING__OTLP_ENDPOINT` → `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` → `OTEL_EXPORTER_OTLP_ENDPOINT` → YAML → unset ⇒ **no-op exporter** |
   | OTLP protocol, headers, timeout, compression, sampler | not modelled by Mint; left entirely to the OTel SDK's own env vars |
   | `service.name`, `service.version`, `deployment.environment.name` | **Mint config only.** `OTEL_SERVICE_NAME` and `OTEL_RESOURCE_ATTRIBUTES` are ignored for these three. |

   The line is: **Mint defers to OTel for how to talk to a backend, and owns who
   the service is.** Identity has to be single-sourced or the `service`/`env`
   fields on every log line (spec § Logging) can disagree with the same fields on
   every span, and a user tracking a reported error from a log to a trace lands
   nowhere. Two mechanical consequences for chunk 08: the OTel `Resource` is
   built explicitly from Mint config and merged *last* so it wins over
   `OTEL_RESOURCE_ATTRIBUTES`; and the exporter is never constructed without an
   explicit endpoint, because the SDK's `localhost:4317` default is the quiet-
   local-`make run` bug.

   Bare `PORT` (Cloud Run, Heroku, Render, Fly) is deliberately *not* read in
   Phase 1 — there are no containers until Phase 2. The seam is this table: it
   gains a row, in `internal/config`, and nowhere else.

9. **Names are derived from one authoring location.** The env var name is
   computed from the same field-path/tag that drives YAML decoding — pydantic
   does it from the model, Go does it by reflecting over the config struct's
   `yaml` tags. No field carries a hand-written env name. This is spec principle
   1 applied to config: adding a field to the struct is the only edit needed for
   it to become configurable from YAML, from the environment, and in
   `--print-config`.

### Worked examples

| config key | depth | env var | notes |
| --- | --- | --- | --- |
| `env` | 1 | `MINT_ENV` | replaces the spec's bare `ENV`; `local\|dev\|staging\|prod` |
| `service.name` | 2 | `MINT_SERVICE__NAME` | wins over `OTEL_SERVICE_NAME`, which is ignored |
| `server.port` | 2 | `MINT_SERVER__PORT` | note this is *not* `WIDGET_SVC_PORT`, which Kubernetes owns |
| `server.read_timeout` | 2 | `MINT_SERVER__READ_TIMEOUT` | leaf with an underscore — the case the single-`_` scheme breaks on |
| `server.admin_port` | 2 | `MINT_SERVER__ADMIN_PORT` | |
| `logging.format` | 2 | `MINT_LOGGING__FORMAT` | replaces the spec's bare `LOG_FORMAT` |
| `logging.level` | 2 | `MINT_LOGGING__LEVEL` | replaces the near-universal bare `LOG_LEVEL` |
| `server.timeouts.read_header` | 3 | `MINT_SERVER__TIMEOUTS__READ_HEADER` | depth 3 *and* an underscore in the leaf |
| `observability.tracing.otlp_endpoint` | 3 | `MINT_OBSERVABILITY__TRACING__OTLP_ENDPOINT` | falls back to `OTEL_EXPORTER_OTLP_*`; unset ⇒ no-op exporter |
| `observability.metrics.namespace` | 3 | `MINT_OBSERVABILITY__METRICS__NAMESPACE` | see [0003](0003-metric-naming-and-labels.md) |
| `database.password` (future) | 2 | `MINT_DATABASE__PASSWORD` | secret-marked in the type; masked by `--print-config` because of the type, not the name |

All eleven rows are produced mechanically by the same rule in both languages;
`docs/config.md` renders this table rather than restating it.

## Alternatives considered

**Prefix = `service_name` upper-snaked (`WIDGET_SVC_`).** The genuinely
attractive property is that two services sharing an env namespace can never
collide, which matters for a shared `.env` at a compose project root or a
ConfigMap consumed by several Deployments via `envFrom`. It loses on a hard
technical fact rather than a preference: Kubernetes already claims
`{SVCNAME}_PORT`, `{SVCNAME}_SERVICE_HOST` and `{SVCNAME}_SERVICE_PORT` for
Docker-link compatibility, by default, and `service_name` is DNS-label-safe
specifically so it can become the k8s Service name. `WIDGET_SVC_PORT` would be
set by the platform to `tcp://10.0.162.149:8080`. Working around it means
requiring `enableServiceLinks: false` on every Pod spec Mint ever ships into —
a Phase 3 constraint imposed by a Phase 1 naming choice, enforced nowhere. Two
smaller costs: a `copier update` that renames a service renames every one of its
env vars, and no shared tooling (a base Helm chart, a debugging human, an agent
reading `AGENTS.md`) can name a Mint config variable without first knowing which
service it is looking at.

**Prefix as a copier question.** Adds an eighth question to a set that
`make parity` diffs, and buys per-service variation of the one thing that most
benefits from being invariant. The property worth having is "`cd` into any Mint
service and you already know the env vars"; a configurable prefix trades that
away for a need nobody has articulated. The constant is one line in each
template if an org ever does need to fork it.

**Single `_` as the level separator (the spec's literal sketch).** Shortest and
most familiar. Rejected on the collision the spike reproduces: it is not
injective the moment a key contains an underscore and a sibling section shares
its first token, and it fails silently — the wrong value is loaded, no error is
raised. Salvaging it means banning underscores inside key names, which forces
`server.readtimeout` and `observability.tracing.otlpendpoint` on the YAML file
and on `--print-config` output, degrading the *readable* representation to
protect the flat one.

**`.NET-style `__` — which is what we chose — but with `:` accepted as an
alias.** ASP.NET Core accepts both. Rejected under decision 4: two spellings per
key, and `:` is not a valid identifier character in POSIX shells, so
`MINT_SERVER:PORT=9000 ./svc` doesn't work without `env`.

**Per-field explicit env names** (Go `env:"MINT_SERVER__READ_TIMEOUT"` tags,
pydantic `validation_alias`). Unambiguous, zero derivation code, and supported
out of the box by `caarlos0/env`. Rejected on spec principle 1: it is a second
authoring location for a fact the struct already states, it drifts from the YAML
tag on the same field, and nothing catches the drift. `kelseyhightower/envconfig`
can't express `__` at all — its nested prefixes are single-underscore — which is
worth recording so chunk 03 doesn't rediscover it.

**Reading `OTEL_EXPORTER_OTLP_ENDPOINT` implicitly by just letting the SDK do
it.** Zero code, standard behavior, and what most services do. Rejected for
three reasons that compound: it puts an env var read outside `internal/config`,
breaking the lint rule the spec demands; `--print-config` then can't show the
endpoint actually in use, defeating the flag's purpose; and the SDK's
`localhost:4317` default means "nothing configured" silently becomes "export to
a Jaeger that isn't there", which is chunk 08's explicit non-goal. Reading it
*in* `internal/config` as an enumerated fallback keeps the standard behavior
users expect and all three properties.

**Honoring bare `ENV` / `LOG_LEVEL` / `LOG_FORMAT` as documented aliases.** The
spec's own prose uses them and they are what a human types from muscle memory.
Rejected because they are the single most-squatted names in any process
environment: CI systems, base images and unrelated libraries all set
`LOG_LEVEL`, and inheriting one of those turns a deploy's log volume into an
accident. If this decision gets overridden, the right shape is a closed,
documented alias list at strictly lower precedence than the `MINT_` form, with
`--print-config` printing the alias it resolved from.

## Consequences

**Easy.** Adding a config field is one edit. Reading `MINT_SERVER__TIMEOUTS__READ_HEADER`
tells you the YAML path without consulting a table. Two Mint services in one
compose file or one Pod get their env from their own `environment:` block or
container `env:` list, which is per-container in both systems, so the shared
constant prefix costs nothing in the normal case. Grepping a deploy manifest for
`MINT_` finds every knob. The scheme is `[A-Z0-9_]+` only, so it is legal in
POSIX shells, `.env` files, Kubernetes env names and Helm values without
escaping.

**Hard — and this is the real cost.** The one case a constant prefix genuinely
loses is a *shared* env source: a root `.env` interpolated into several compose
services, or one ConfigMap `envFrom`-ed by several Deployments. Under `MINT_`
those two services cannot have different ports. The mitigation is to scope the
source (per-service `environment:`/ConfigMap), which is correct practice anyway,
but it is a real constraint someone will hit and it must be documented in
`docs/config.md` rather than discovered.

**Go/Python asymmetries this leaves open.** All three are pydantic being *more*
permissive than the Go loader, not less, so no supported usage diverges — but
each is a place a Python service accepts input a Go service rejects, and the
parity suite must therefore assert the *negative*:

| behavior | Python | Go | resolution |
| --- | --- | --- | --- |
| `MINT_SERVER='{"port": 7777}'` (whole section as JSON) | works — spike printed `section-as-JSON -> 7777` | no equivalent | **unsupported.** Documented as such; parity test asserts the Go and Python services reject/ignore it identically, or at minimum that nothing Mint generates uses it. Note the failure mode: `MINT_SERVER=anything-non-JSON` raises `SettingsError` in Python and is simply ignored in Go. |
| lower/mixed-case names | free (`case_sensitive=False`) — spike printed `lowercase env accepted -> 9999` | ~3 lines to upper-case `os.Environ()` keys | closed in Go's favor: both case-insensitive, canonical form documented as `UPPER_SNAKE`. |
| two vars normalizing to one name | pydantic picks one, silently | Go would take last-wins | closed by hand in both: ~10 lines each, startup error naming both variables. |

The `--print-config` "which source won" column also has to name the *variable*,
not just "env", precisely because of the fallback chain in decision 8 — a value
sourced from `OTEL_EXPORTER_OTLP_ENDPOINT` must say so.

The scalars-only rule (decision 5) exists because of the first row of that
table: pydantic's default treatment of any complex-typed field is
"JSON-decode the env var", which Go would have to reimplement to match,
including its error text. Keeping the env surface scalar keeps the two loaders
provably equivalent instead of approximately equivalent.

**Chunk 03 constraint.** If a Go config library is used instead of a hand-rolled
reflective loader, it must be one whose env-name derivation can be configured to
produce exactly these names from the existing struct tags. `spf13/viper`
(`SetEnvPrefix("MINT")` + `SetEnvKeyReplacer(strings.NewReplacer(".", "__"))`)
and `knadh/koanf`'s env provider callback both can; `kelseyhightower/envconfig`
cannot; `caarlos0/env` can only via per-field tags, which decision 9 rules out.
Note also that no off-the-shelf Go option gives the "report every invalid field
at once" behavior the spec requires for free, so some of that ~40 lines is
unavoidable regardless — the spike's multi-error output is the target format:

```
multi-error output (3 errors):
  - server.port (MINT_SERVER__PORT): "not-a-number" is not an integer
  - server.timeouts.read_header (MINT_SERVER__TIMEOUTS__READ_HEADER): "abc" is not a duration
  - env (MINT_ENV): "bogus" is not one of local, dev, staging, prod
```

**To reverse it.** Changing the prefix is a one-constant edit in each template
plus a `_migrations` entry, but every deployed service's env must change in the
same release — this is a fleet-coordinated change, not a template update.
Changing the separator is worse: it is a `_migrations` entry *and* silent
misconfiguration for any service that updates the template without updating its
deploy manifest, because the old names simply stop matching and defaults take
over. If either is going to change, it has to change before the first service
is minted.
