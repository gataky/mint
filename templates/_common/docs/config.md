# Configuration

> **Source of truth** for this service's configuration precedence, its
> environment variable naming scheme, and its secrets stance. The README links
> here rather than restating it. This file is minted from Mint's
> `templates/_common/`, so the Go and Python versions of it are the same file
> — a rule stated here holds for both languages, and Mint's `make parity`
> checks that they obey it.

## Two sources, and only two

Highest precedence first:

1. **Environment variables**
2. **`config/config.local.yaml`** — your machine, gitignored, optional
3. **`config/config.yaml`** — committed defaults

There is deliberately **no third source**. No JSON, no TOML, no remote
config, no command-line flags that set values. A service boots correctly with
no environment and no local file at all; `config/config.yaml` alone is a
complete configuration.

`--print-config` shows which source won for every key. Reach for it before
guessing.

### The application never reads `.env`

A `.env` file next to this service is **direnv's business, not the
application's**. `.envrc` runs `dotenv_if_exists`, so those values become
ordinary environment variables before any process starts.

The consequence is worth stating plainly rather than discovering:
**values in `.env` arrive as environment variables and therefore beat
`config/config.local.yaml`.** If a key seems to ignore your local YAML, check
`.env` first — `--print-config` will say `env`.

Nothing in the service's code reads `.env`, parses it, or knows it exists.

## Environment variable names

```
MINT_ + UPPER( config key path, joined with __ )
```

- The prefix is the constant `MINT_`. It is **not** derived from the service
  name — Kubernetes already injects `<SVCNAME>_PORT` for every Service, so a
  service-derived prefix would collide with values like
  `tcp://10.0.162.149:8080`.
- `__` separates levels. A single `_` is **never** a separator, so a key's own
  underscores survive: `server.read_timeout` → `MINT_SERVER__READ_TIMEOUT`.
- Config keys are `snake_case` matching `^[a-z][a-z0-9_]*$` and may not
  contain `__`. That invariant makes the mapping a **bijection** — every
  variable name decodes to exactly one key — and it is asserted at startup
  over the whole config type, not merely documented here.
- Names are **derived**, never hand-written. Adding a field to the config type
  is the only edit needed for it to be settable from YAML, from the
  environment, and visible in `--print-config`.

| config key | environment variable |
| --- | --- |
| `env` | `MINT_ENV` |
| `service.name` | `MINT_SERVICE__NAME` |
| `server.port` | `MINT_SERVER__PORT` |
| `server.admin_port` | `MINT_SERVER__ADMIN_PORT` |
| `server.read_timeout` | `MINT_SERVER__READ_TIMEOUT` |
| `server.timeouts.read_header` | `MINT_SERVER__TIMEOUTS__READ_HEADER` |
| `logging.format` | `MINT_LOGGING__FORMAT` |
| `logging.level` | `MINT_LOGGING__LEVEL` |
| `observability.tracing.otlp_endpoint` | `MINT_OBSERVABILITY__TRACING__OTLP_ENDPOINT` |
| `observability.metrics.namespace` | `MINT_OBSERVABILITY__METRICS__NAMESPACE` |
| `database.password` *(illustrative)* | `MINT_DATABASE__PASSWORD` |

### There are no aliases

**Bare `ENV`, `LOG_LEVEL`, `LOG_FORMAT` and `PORT` are read by nothing in this
service.** Use `MINT_ENV`, `MINT_LOGGING__LEVEL`, `MINT_LOGGING__FORMAT`,
`MINT_SERVER__PORT`.

`LOG_LEVEL` in particular is the most-squatted name in any process
environment; inheriting a CI system's value would turn a deploy's log volume
into an accident. And two names for one key would force `--print-config`'s
"which source won" column to explain a precedence rule *between environment
variables*, which is the confusion it exists to remove.

### Scalars only

Environment variables carry scalars — no lists, no maps, no JSON. Setting a
whole section as a JSON blob is unsupported. If a list is ever genuinely
needed it will be comma-separated with a documented parser, added to both
languages in one change.

### Other rules

- **Case-insensitive matching**, with `UPPER_SNAKE` canonical. Two variables
  that normalize to the same name fail startup, naming both.
- **Empty is a value, not an absence.** `MINT_SERVER__PORT=` is "present and
  empty" and fails validation naming the variable. It does not fall through
  to YAML.

### One cost of a constant prefix

Two Mint services sharing a single environment source — a root `.env` in a
compose project, or one ConfigMap `envFrom`-ed by several Deployments —
**cannot have different ports**, because both read `MINT_SERVER__PORT`.

The mitigation is to scope environment per service, which is correct practice
anyway. It is documented here so it is discovered by reading rather than by
debugging.

## Environments

`MINT_ENV` is one of `local`, `dev`, `staging`, `prod`. Anything else is a
**startup error**, not a silent fallback to a default.

`local` is the default when unset, and it is what selects the human-readable
log tier and the quiet no-op trace exporter.

## Variables this service does not own

Configuration is read in exactly one place, but a few variables belong to
other standards. The rule: **defer to OpenTelemetry for how to reach a
backend; own who this service is.**

| concern | resolution order, highest first |
| --- | --- |
| OTLP endpoint | `MINT_OBSERVABILITY__TRACING__OTLP_ENDPOINT` → `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` → `OTEL_EXPORTER_OTLP_ENDPOINT` → YAML → unset means **no exporter** |
| OTLP protocol, headers, timeout, compression, sampler | not modelled here; the OTel SDK's own variables apply |
| `service.name`, `service.version`, `deployment.environment.name` | **this service's config only** — `OTEL_SERVICE_NAME` and `OTEL_RESOURCE_ATTRIBUTES` are ignored for these three |

Identity is single-sourced deliberately. If it weren't, the `service` and
`env` fields on a log line could disagree with the same fields on a span, and
anyone tracing a reported error from a log would land nowhere.

## Validation

Configuration is validated at startup. An invalid value stops the process
rather than surfacing later as a request-time failure.

**Every invalid field is reported at once**, each naming both the config key
and the variable that sets it:

```
config: 3 errors
  - server.port (MINT_SERVER__PORT): "not-a-number" is not an integer
  - server.timeouts.read_header (MINT_SERVER__TIMEOUTS__READ_HEADER): "abc" is not a duration
  - env (MINT_ENV): "bogus" is not one of local, dev, staging, prod
```

Fixing one error at a time across three restarts is the experience this
avoids.

## Secrets

- **Never** in `config/config.yaml` or `config/config.local.yaml`. Both are
  read by humans and one is committed.
- Environment variables only.
- Secret fields are **marked in the config type**, and masking follows from
  the type — not from the field's name, and not from remembering to mask at
  each call site. A marked field is masked in `--print-config`, in logs, and
  in error messages, automatically.

A real secrets provider would be wired in `internal/config` and nowhere else.

## Adding a third source

Only if there is a concrete need. The two-source rule exists because an
unused code path in a template is worse than no path — every service
inherits its maintenance and documentation cost forever.

1. Implement the source interface in `internal/config` (`Name()` and a load
   step returning key/value pairs).
2. Insert it into the ordered source list at the right precedence, in **both**
   languages.
3. Add its name to the source-list test — the one asserting the order is
   exactly `["yaml", "env"]` today.
4. Update the precedence list at the top of this file.
5. Make `--print-config` able to name it in the "source" column.

Nothing else in the service changes. That is the whole point of the ordered
list being the only place precedence is expressed.
