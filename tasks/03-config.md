# 03 — Configuration

**Spec:** § Configuration
**Depends on:** 02. **ADRs 0002 (env var naming) and 0006 (sources) are
binding here**; 0003 § 3 fixes the metrics namespace key.
**Size:** M
**Standing rules:** [tasks/README.md](README.md#standing-rules--these-apply-to-every-chunk)

## Goal

`internal/config` becomes the only place in a generated service that reads an
environment variable or a file, in both languages, with identical precedence,
identical validation behavior, and a way to see what actually resolved.

## Do

1. **Typed config** — one struct (Go) / one pydantic `BaseSettings` model
   (Python), with defaults sane enough that a service boots with zero
   configuration. Sections at minimum: service identity (name, version,
   owner, env), server (port, admin_port, timeouts), logging (format,
   level), observability (`tracing.otlp_endpoint`, `metrics.namespace`).

   `observability.metrics.namespace` defaults to `service_name` with `-` → `_`
   (ADR 0003 § 3); the copier `service_name` validator is what guarantees the
   result is a legal Prometheus name prefix.

2. **Precedence: env > YAML, and exactly those two** — ADR 0006. Load
   `config/config.yaml`, overlay `config/config.local.yaml` if present,
   overlay environment variables.

   **Python does not get this by default and must be forced into it.**
   `pydantic_settings.BaseSettings` builds from a **four**-source tuple —
   `init_settings`, `env_settings`, `dotenv_settings`,
   `file_secret_settings` — and a naive subclass silently reads `.env` and
   `/run/secrets` while its Go twin does not. The spike measured a `.env`
   beating YAML with nobody writing a line of code. Override
   `settings_customise_sources` to return exactly the two sources, **with a
   comment above it saying it exists to hold parity with Go** — its purpose
   is to remove functionality, so without that comment someone will helpfully
   delete it in a future cleanup.

   Never set `env_file` on `SettingsConfigDict`.

3. **Build the loader around an ordered source list, in both languages.** Go:
   a small interface (`Name() string`, `Load() (map[string]string, error)`)
   and an ordered `[]Source` from lowest to highest precedence. Python: the
   tuple returned by `settings_customise_sources`. A third source is then one
   type and one insertion at the right index, in both languages, and nowhere
   else — that is the seam ADR 0006 documents instead of shipping.

   **Both languages expose their ordered source list by name.** A test in
   each asserts it equals exactly `["yaml", "env"]`, and `make parity` diffs
   the two lists against each other and against `docs/config.md`. That check
   is what turns a pydantic default silently reintroducing `dotenv_settings`
   into a build failure instead of a production surprise.

4. **Command-line flags are not a config source.** `--print-config` and a
   flag pointing at the YAML file's location are fine; **no flag sets a config
   value.** A flag that sets a value is a third source wearing a disguise.

5. **Env var naming, per ADR 0002 — this is a bijection, not a convention:**

   ```
   MINT_ + UPPER( join(config key path, "__") )
   ```

   - The prefix is the **constant** `MINT_`. Not derived from `service_name`
     — Kubernetes already injects `{SVCNAME}_PORT=tcp://10.0.162.149:8080`
     for every Service by default, and Mint's `service_name` is DNS-label-safe
     specifically so it can *be* that Service name. It is one named constant
     (`const EnvPrefix = "MINT_"` / `env_prefix="MINT_"`) so a fork changes it
     in one place.
   - **`__` between levels. A single `_` is never a level separator**; a
     key's own underscores are preserved. `server.read_timeout` →
     `MINT_SERVER__READ_TIMEOUT`. The single-`_` form collides
     (`server.read_timeout` vs `server.read.timeout`) and loses silently.
   - Config keys are `snake_case`, match `^[a-z][a-z0-9_]*$`, and must not
     contain `__`. **Assert this at startup over the whole config type**, and
     assert it in the parity check. With that invariant the mapping is a
     bijection and every env var name decodes to exactly one config key.
   - **Names are derived from one authoring location** — the same field
     path / `yaml` tag that drives YAML decoding. No field carries a
     hand-written env name. Adding a field to the struct is the only edit
     needed for it to be configurable from YAML, from the environment, and in
     `--print-config`.
   - **Env vars carry scalars only.** No lists, no maps, no JSON. Python's
     `MINT_SERVER='{"port": 7777}'` whole-section-as-JSON behaviour is
     **unsupported**, and the parity suite asserts the negative — note the
     asymmetry it's guarding: a non-JSON value there raises `SettingsError` in
     Python and is simply ignored in Go.
   - Case-insensitive matching in both (Go upper-cases keys from
     `os.Environ()`; pydantic already does at `case_sensitive=False`), with
     `UPPER_SNAKE` documented as canonical. **Two variables normalizing to
     one name is a startup error naming both** — roughly ten lines in each
     language, and pydantic would otherwise pick one silently.
   - **Empty string is a value, not an absence.** `MINT_SERVER__PORT=` is
     "present, empty" and fails validation with a message naming the
     variable. It does not fall through to YAML. `LookupEnv`, not `Getenv`.

6. **No aliases. One canonical name per key.** This **overrides the spec's
   own prose**: `ENV` becomes `MINT_ENV`, `LOG_FORMAT` becomes
   `MINT_LOGGING__FORMAT`, `LOG_LEVEL` becomes `MINT_LOGGING__LEVEL`. Bare
   `ENV`, `LOG_LEVEL`, `LOG_FORMAT` and `PORT` are read by **nothing** in a
   Mint service. `LOG_LEVEL` in particular is the single most-squatted name
   in any process environment, and inheriting a CI system's value turns a
   deploy's log volume into an accident. Two names per key would also force
   `--print-config`'s "which source won" column to explain a precedence rule
   *between env vars*, which is the confusion it exists to remove.

7. **Foreign env vars: defer on transport, own identity** (ADR 0002 § 8).
   `internal/config` is still the only place that reads the environment, and
   it reads a short, explicitly enumerated list of variables Mint does not
   own:

   | concern | resolution order (highest first) |
   | --- | --- |
   | OTLP endpoint | `MINT_OBSERVABILITY__TRACING__OTLP_ENDPOINT` → `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` → `OTEL_EXPORTER_OTLP_ENDPOINT` → YAML → unset ⇒ **no-op exporter** |
   | OTLP protocol, headers, timeout, compression, sampler | not modelled by Mint; left to the OTel SDK's own env vars |
   | `service.name`, `service.version`, `deployment.environment.name` | **Mint config only.** `OTEL_SERVICE_NAME` and `OTEL_RESOURCE_ATTRIBUTES` are ignored for these three. |

   Identity has to be single-sourced or the `service`/`env` fields on a log
   line can disagree with the same fields on a span, and someone tracking a
   reported error from a log to a trace lands nowhere. Bare `PORT` (Cloud
   Run, Heroku, Fly) is deliberately **not** read in Phase 1; the seam is
   this table gaining a row, in `internal/config`, and nowhere else.

8. **`MINT_ENV` values** — `local | dev | staging | prod`, and nothing else.
   Any other value is a startup error, not a silent fallback.

9. **Validation that reports every invalid field at once.** Pydantic does
   this natively; Go needs deliberate effort to match it, and no off-the-shelf
   Go option gives it for free. Collect errors, don't return on the first.
   The target output format, identical in both languages, is ADR 0002's:

   ```
   multi-error output (3 errors):
     - server.port (MINT_SERVER__PORT): "not-a-number" is not an integer
     - server.timeouts.read_header (MINT_SERVER__TIMEOUTS__READ_HEADER): "abc" is not a duration
     - env (MINT_ENV): "bogus" is not one of local, dev, staging, prod
   ```

   Each line names the config key **and** the env var it maps to.

10. **If you reach for a Go config library**, it must derive exactly these
    names from the existing struct tags. `spf13/viper`
    (`SetEnvPrefix("MINT")` + `SetEnvKeyReplacer(".", "__")`) and
    `knadh/koanf`'s env provider callback both can.
    `kelseyhightower/envconfig` **cannot** — its nested prefixes are
    single-underscore. `caarlos0/env` can only via per-field tags, which is a
    second authoring location and is ruled out. A hand-rolled reflective walk
    is ~40 lines and is a legitimate choice.

11. **Secret marking.** Fields marked secret in the type are masked
    automatically anywhere config is rendered — `--print-config`, logs,
    errors. Masking is a property of the type, not of call-site discipline,
    and not of the field's name.

12. **`--print-config` and `make config`** — dump the effective resolved
    config with secrets masked, annotating each key with which source won
    (default / yaml / local yaml / env). Identical output format in both
    languages. For a value that came from the ADR 0002 § 8 fallback chain,
    **the annotation must name the variable**, not just "env" — a value
    sourced from `OTEL_EXPORTER_OTLP_ENDPOINT` has to say so.

13. **Lint rule**: nothing outside `internal/config` reads an env var. A grep
    in `make lint` is sufficient. Make it fail with a message that names the
    offending file and points at the rule. Note that this rule is why chunk
    08 must call `prometheus_client.disable_created_metrics()` rather than
    set `PROMETHEUS_DISABLE_CREATED_SERIES`, and why the OTLP endpoint is
    read here rather than left to the SDK.

14. **`docs/config.md`** — the source of truth: the two sources and their
    precedence, the env var naming scheme with ADR 0002's eleven worked
    examples rendered from the same rule the code uses, the `MINT_ENV`
    values, the secrets stance, the five-step checklist for adding a third
    source if one is ever justified, and — prominently, not in a footnote —
    **that the application never reads `.env`, and that `.env` is direnv's
    business** via `dotenv_if_exists` in `.envrc`. Note the consequence
    honestly: values from `.env` arrive as environment variables and
    therefore beat `config/config.local.yaml`.

    Also document the one real cost of a constant prefix: two Mint services
    sharing a single env source (a root compose `.env`, one ConfigMap
    `envFrom`-ed by several Deployments) cannot have different ports. The
    mitigation is per-service scoping, which is correct practice anyway — but
    it should be documented rather than discovered.

15. **`config/config.yaml`** with documented defaults and
    `config/config.local.yaml.example` committed; `config.local.yaml` and
    `.env` gitignored.

## Out of scope

Logging implementation (chunk 04) — config only needs to *carry* the logging
settings. Tracing/metrics wiring (chunk 08) — same; this chunk owns the
endpoint *resolution* table, not the exporter. Don't build a secrets
provider; just leave the documented seam.

## Deliverables

- `internal/config` in both templates, with tests
- `docs/config.md`
- `config/config.yaml` and `config.local.yaml.example` in both templates
- `make config` working and identical in both
- Env-var lint check wired into `make lint`

## Acceptance criteria

- A generated service boots with no config files and no env vars set.
- Precedence test: the same key set in YAML and env resolves to the env
  value, in both languages.
- **Source-list test**: both languages report their ordered sources as
  exactly `["yaml", "env"]`. A `.env` file sitting next to the Python service
  changes nothing about its resolved config. Demonstrate.
- **Env-name bijection test**: walking the whole config type produces no
  duplicate env var names, and every key matches `^[a-z][a-z0-9_]*$` without
  `__`. `MINT_SERVER__READ_TIMEOUT` resolves `server.read_timeout` in both
  languages.
- Two env vars normalizing to one canonical name fail startup with a message
  naming both.
- `MINT_SERVER__PORT=` (empty) fails validation naming the variable — it does
  not fall through to YAML.
- Multi-error test: three invalid values produce three errors in one
  message, in both languages, in the same format, each naming both the config
  key and the env var.
- `MINT_ENV=bogus` fails at startup with a message naming the valid values.
  Bare `ENV=bogus` is ignored entirely.
- A field marked secret appears masked in `make config` output and never
  appears unmasked in any output the service produces.
- `make config` output for the two generated services is diff-identical
  modulo the service name.
- `make lint` fails when an env var read is added outside `internal/config`.
  Demonstrate, then revert.
- `scripts/parity.sh` gains a check diffing `make config` output between the
  two generated services, **and** the source-list assertion from item 3
  (both languages agree with each other and with `docs/config.md`).

## Flag back before finishing

- Any Go/Python asymmetry in multi-error validation output you couldn't
  fully close — this is the most likely place in this chunk for the two
  languages to diverge, and it's better flagged than papered over. ADR 0002
  already names three asymmetries (section-as-JSON, case handling, duplicate
  normalization) and how each is closed; flag anything *else* you find.
- If the derived-name rule met a config shape it couldn't express — a field
  that genuinely needs a list, say — flag it rather than adding a JSON
  escape hatch. The scalars-only rule exists because pydantic's default for a
  complex-typed field is "JSON-decode the env var", which Go would have to
  reimplement including its error text.

*Settled, do not re-open:* the `MINT_` prefix, the `__` separator, the
absence of aliases for `ENV`/`LOG_LEVEL`/`LOG_FORMAT`/`PORT`, and the
two-source rule. ADRs 0002 and 0006, approved.
