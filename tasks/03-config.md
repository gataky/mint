# 03 — Configuration

**Spec:** § Configuration
**Depends on:** 02 (and ADR 0002 for the env var scheme, 0006 for sources)
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
   level), observability (OTLP endpoint, metrics namespace).

2. **Precedence: env > YAML.** No third source — see ADR 0006. Load
   `config/config.yaml`, overlay `config/config.local.yaml` if present,
   overlay environment variables.

3. **Env var naming** per ADR 0002, identical in spirit across languages and
   differing only in casing convention. Document the mapping from nested
   config key to flat env var name.

4. **`ENV` values** — `local | dev | staging | prod`, and nothing else. Any
   other value is a startup error, not a silent fallback.

5. **Validation that reports every invalid field at once.** Pydantic does
   this natively; Go needs deliberate effort to match it. Collect errors,
   don't return on the first. Output format identical in both languages.

6. **Secret marking.** Fields marked secret in the type are masked
   automatically anywhere config is rendered — `--print-config`, logs,
   errors. Masking is a property of the type, not of call-site discipline.

7. **`--print-config` and `make config`** — dump the effective resolved
   config with secrets masked, annotating each key with which source won
   (default / yaml / local yaml / env). Identical output format in both
   languages.

8. **Lint rule**: nothing outside `internal/config` reads an env var. A grep
   in `make lint` is sufficient. Make it fail with a message that names the
   offending file and points at the rule.

9. **`docs/config.md`** — the source of truth: precedence, the env var
   naming scheme with worked examples, the `ENV` values, the secrets stance,
   and where a third source would go if ever justified. Both generated
   READMEs link to it.

10. **`config/config.yaml`** with documented defaults and
    `config/config.local.yaml.example` committed; `config.local.yaml`
    gitignored.

## Out of scope

Logging implementation (chunk 04) — config only needs to *carry* the logging
settings. Tracing/metrics wiring (chunk 08) — same. Don't build a secrets
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
- Multi-error test: three invalid values produce three errors in one
  message, in both languages, in the same format.
- `ENV=bogus` fails at startup with a message naming the valid values.
- A field marked secret appears masked in `make config` output and never
  appears unmasked in any output the service produces.
- `make config` output for the two generated services is diff-identical
  modulo the service name.
- `make lint` fails when an env var read is added outside `internal/config`.
  Demonstrate, then revert.
- `scripts/parity.sh` gains a check diffing `make config` output between the
  two generated services.

## Flag back before finishing

- The final env var naming scheme as built, if it deviated at all from ADR
  0002 once it met real nested config.
- Any Go/Python asymmetry in multi-error validation output you couldn't
  fully close — this is the most likely place in this chunk for the two
  languages to diverge, and it's better flagged than papered over.
