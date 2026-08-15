# AGENTS.md — the Mint template repo

Context for a coding agent working on **this repo**. If you're looking at a
service that was *generated* from these templates, you want that service's
own AGENTS.md instead.

## What Mint is

A monorepo that generates microservices in Go or Python from a single,
consistent set of Copier templates. The point is not the code generation —
it's that a developer or an agent dropped into a generated service finds the
same architecture, the same Makefile targets, and the same log schema
regardless of which language it is.

## Two principles that govern everything

1. **One set of facts, several representations.** Any fact appearing in more
   than one place — an operation name, a log field, a Makefile target, a
   config key — has exactly one authoring location and is generated or
   checked everywhere else. A hand-written description that drifts from
   actual behavior is exactly as bad as a stale Swagger comment.
2. **Guarantees are mechanical, not aspirational.** "Keep these identical"
   is not a requirement; a check that exits non-zero when they diverge is.
   If you add a rule, add the check that enforces it in the same change.

## Where things live

| what | where |
| --- | --- |
| The specification | [`prompt.md`](prompt.md) — the durable statement of what Mint must be |
| Implementation chunks | [`tasks/`](tasks/README.md) — ordered, one per agent session |
| Decisions and why | [`docs/decisions/`](docs/decisions/README.md) |
| Shared source-of-truth docs | `docs/architecture.md`, `logging.md`, `config.md`, `agents.md`, `testing.md` |
| Language-agnostic template files | `templates/_common/` |
| The two templates | `templates/go-service/`, `templates/python-service/` |
| Drift + smoke harnesses | `scripts/parity.sh`, `scripts/verify-template.sh` |

Run `make help` for this repo's targets.

## Rules for working here

- **Never change one language without the other.** A copier question, a
  Makefile target, a log field, or a config key added to Go must be added to
  Python in the same change. This is the single most important rule in the
  repo, and `make parity` exists to enforce it.
- **`templates/_common/` is for files that are genuinely identical.** If a
  file needs a language-specific word in it, it does not belong there.
  Resist `[% if language == "go" %]`.
- **Jinja delimiters are `[[ ]]` / `[% %]` / `[# #]`**, not the defaults —
  Phase 2 brings GitHub Actions and its `${{ }}` would collide.
- **Pin every version.** No floating dependencies, no "latest at generation
  time" resolution — two developers minting a week apart must get identical
  toolchains.
- **Write an ADR** for any call the spec doesn't dictate. Supersede, don't
  edit.
- **Leave it green**: `make parity`, `make verify`, and `make test` pass
  before you're done.

## Deliberately not built

Dockerfiles, docker-compose, CI, Kubernetes manifests, MCP servers, and
authentication. Each is deferred with a named seam that keeps it cheap to add
later — see the deferral table in `prompt.md` § Scope and the ADRs it points
at. Don't build these; don't preclude them either.

## Status

Phase 1, in progress. See [`tasks/README.md`](tasks/README.md) for the chunk
order and which are done.
