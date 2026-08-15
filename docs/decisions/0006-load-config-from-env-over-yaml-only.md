# 0006 — Load config from environment variables over YAML, and from nothing else

**Status:** accepted (2026-08-14)
**Date:** 2026-08-14
**Chunk:** [01 — Decisions and ADRs](../../tasks/01-decisions.md)

## Context

An earlier draft of the spec allowed a JSON config source "where there's a
concrete reason." No concrete reason materialised, and the spec now states the
precedence as environment variables > YAML file, with deliberately no third
source. This ADR records why, states precisely where a third source would be
added if one is ever justified, and settles the `.env` question that the spec
leaves open.

The governing argument is not about JSON. It is about what a template costs:

> An unused code path in a template is worse than no path. Every generated
> service inherits its maintenance cost, its documentation cost, and its
> surface area in `--print-config`, in `docs/config.md`, and in the parity
> check — forever, and in two languages. A path that nobody exercises is a
> path whose breakage nobody notices.

Two sources is already the minimum that is genuinely useful: YAML gives a
reviewable, checked-in default set that makes `make run` work with zero setup,
and environment variables give the twelve-factor override that container
platforms actually supply. A third source has to earn its place against that
baseline, and JSON does not: it expresses exactly what YAML expresses, less
readably, with no comments.

### What the spike found, and it changes the decision's shape

The interesting discovery is not about JSON. It is that **"no third source" is
not the default in Python and has to be actively enforced**, whereas in Go it
is the default because Go has no config framework at all.

`pydantic_settings.BaseSettings` builds its values from a default tuple of
four sources. Verified against pydantic-settings 2.15.0 / pydantic 2.13.4:

```
default source slots pydantic offers: ['init_settings', 'env_settings',
                                       'dotenv_settings', 'file_secret_settings']
```

A naive `BaseSettings` subclass therefore silently has more sources than the
spec allows, and one of them wins over YAML without anyone writing a line of
code:

```
naive  server_port = 9999   <- .env won, silently
strict server_port = 8080   <- .env ignored; only env vars + (yaml)
```

`strict` differs from `naive` by one overridden classmethod. Without that
override, a generated Python service reads `.env` and `/run/secrets` while its
Go twin does not — a parity break in the config layer, which is the one layer
where a silent difference is most likely to cause a production incident and
least likely to be noticed in review.

### The `.env` question

direnv is already in the stack, and direnv 2.37.1 ships `dotenv` and
`dotenv_if_exists` in its stdlib. That resolves the question cleanly rather
than leaving it ambiguous: a developer who wants a `.env` file can have one,
loaded by direnv, and by the time either process starts, its contents are
ordinary environment variables. It is the *same* source, not a new one. It
works identically in Go and Python, requires zero application code, zero
dependency (`godotenv` in Go, `env_file=` in Python), and cannot perturb the
documented precedence because it resolves before the process exists.

## Decision

**Exactly two config sources, in this precedence: environment variables >
YAML file.** No JSON. No TOML. No `.env` read by the application. No
`/run/secrets` directory source. No remote config service.

**The application never reads `.env`.** The Python template must not set
`env_file` on `SettingsConfigDict`, and must override
`settings_customise_sources` to return exactly the two sources — dropping
`dotenv_settings` and `file_secret_settings`, and dropping `init_settings`
except where the tests need it. `.envrc` may use `dotenv_if_exists .env`, and
`docs/config.md` documents that as the supported way to keep local overrides
that must not be checked in — noting that the values arrive as environment
variables and therefore win over `config/config.local.yaml`, which is the
correct and documented behaviour, not a special case. `.env` is gitignored
alongside `config/config.local.yaml`.

**Command-line flags are not a config source.** The service accepts
`--print-config` and may accept a flag pointing at the YAML file's location,
but no flag sets a config *value*. A flag that sets a value is a third source
wearing a disguise, and it is the one that would sneak in most easily.

**Where a third source goes, precisely.** One place per language, and it must
be both places or neither:

- **Go** — `internal/config/`, in the ordered slice the loader iterates. The
  loader is built around a small interface (`Name() string`,
  `Load() (map[string]string, error)`) and an ordered `[]Source` from lowest
  to highest precedence. A third source is: one type implementing the
  interface, one insertion at the correct index in that slice, and nothing
  else. No caller changes.
- **Python** — `internal/config/`, in `Settings.settings_customise_sources`.
  It returns a tuple in precedence order; a third source is one
  `PydanticBaseSettingsSource` inserted at the correct index in that tuple.

Adding one is not complete until all five of these land together, and
`docs/config.md` says so:

1. the source in both languages, at the same precedence index;
2. its name in `--print-config`'s per-key source annotation, in both;
3. a row in `docs/config.md`'s precedence table;
4. a precedence test in both languages proving the new source loses to
   everything above it and beats everything below it;
5. the parity check's source-list assertion updated — see below.

**The rule is mechanically enforced, not documented and hoped for.** Both
languages expose their ordered source list by name, a test asserts it equals
exactly `["yaml", "env"]`, and `make parity` diffs the two lists against each
other and against `docs/config.md`. That check is what makes a pydantic
default silently reintroducing `dotenv_settings` a build failure rather than a
production surprise. It belongs in chunk 03.

## Alternatives considered

**Add JSON as a third source.** The original draft's option. It buys nothing:
JSON is a strict subset of YAML in expressiveness, cannot carry comments,
and no deployment platform in the intended stack supplies JSON config that
YAML could not equally receive. The one honest argument for it — "a
config-generating tool emits JSON" — is answered by the fact that YAML parsers
accept JSON documents, so a JSON file can simply be named `config.yaml` if
that day comes. Lost on cost/benefit with no benefit on the scale.

**Add a `.env` source in the application.** Genuinely tempting, because it is
what most Python developers expect and pydantic offers it for free. Rejected
on three counts. It is not free in Go — it means a dependency (`godotenv`) in
every generated Go service for a local-development convenience, in violation
of the spec's dependency-justification rule. It creates a real precedence
puzzle: `.env` sits between YAML and the real environment, so `docs/config.md`
grows a rule that only exists to explain an ordering nobody needed. And direnv
already solves the problem strictly better — earlier in the lifecycle, with no
code, no dependency, and no new precedence rule. The decision is therefore not
"no `.env` files"; it is "`.env` files are direnv's business, not the
application's," and that distinction is what `docs/config.md` records.

**Add a secrets-directory source (`/run/secrets`) now.** Kubernetes and Docker
mount secrets as files, and this is where the pressure for a third source will
genuinely come from — it is a far stronger candidate than JSON. It is
nonetheless deferred, because Phase 1's stated stance is that secrets come
from environment variables only, and both Kubernetes and Docker can project a
mounted secret into an environment variable. Deferring it costs nothing today
and this ADR names exactly where it would go if Phase 3 decides that
projection is unacceptable. Note that pydantic *already offers*
`file_secret_settings` for this, which is precisely why the Python override
above must be deliberate: the tempting source is one that already exists and
is being switched off on purpose.

**Allow YAML to beat environment variables in local development.** Considered
because the `.env`-via-direnv decision means a developer's `.envrc` silently
outranks their `config.local.yaml`, which will surprise someone. Rejected: a
precedence order that inverts by environment is the kind of rule that is
correct in the document and wrong in everyone's head. `--print-config`
annotating each key with the winning source is the answer to that surprise,
and it is already required by the spec.

## Consequences

**What this makes easy.** `docs/config.md`'s precedence section is two lines
and cannot grow ambiguous. `--print-config`'s source annotation has a closed
set of exactly two values, so its output is diffable between languages in the
parity check without normalization. A developer or an agent debugging
"why is this value X" has two places to look and a command that names which
one won.

**What this makes hard, honestly.** Anyone arriving from a Python codebase
will expect `.env` to work and will find that it does not until they read
`.envrc` — so `docs/config.md` and the generated README have to answer that
question prominently rather than in a footnote. And the Python template now
carries a non-obvious override whose *purpose is to remove functionality*;
without a comment above it explaining that it exists to hold parity with Go,
someone will helpfully delete it in a future cleanup. That comment is a
required part of chunk 03, and the parity check is the backstop for when the
comment fails.

**What we give up.** Any deployment target that can supply neither environment
variables nor a file at a known path is unsupported. No such target is in
scope for Phases 1–3.

**What would reverse this.** A concrete requirement that neither source can
meet — the realistic one being a secrets manager (Vault, AWS Secrets Manager)
whose values must not transit an environment variable. That is a real
possibility, which is why the loader is built around an ordered list of
sources rather than two hard-coded reads, and why the seam is documented as
living in `internal/config` and nowhere else. The cost of being wrong here is
one type and one slice insertion per language — deliberately cheap, so that
"we might need a third source someday" is not an argument for shipping one
now.
