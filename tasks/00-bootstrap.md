# 00 — Bootstrap the mint repo

**Spec:** § Repo layout, § Decisions
**Depends on:** nothing
**Size:** S
**Standing rules:** [tasks/README.md](README.md#standing-rules--these-apply-to-every-chunk)

## Goal

Turn an empty directory into a git repo with the skeleton the rest of the
work hangs off. No templates, no service code — just the shape, the tooling,
and the top-level Makefile.

## Starting state

The repo is **already `git init`'d**, on branch `main`, with **zero
commits**. Untracked: `prompt.md`, `tasks/`, `.tool-versions`, `.claude/`.
Do not re-init.

Verified present: `go` 1.26.5, `python` 3.14.6, `asdf` 0.20.0, `direnv`
2.37.1, `git` 2.55.0, `jq` 1.8.2. Two things are broken and this chunk fixes
them:

- **`uv` doesn't resolve.** Root `.tool-versions` pins `uv 0.12.5`, but asdf
  only has 0.11.31 and 0.12.0 installed, so `asdf which uv` fails →
  `asdf install uv 0.12.5`. Install the pinned version; don't downgrade the
  pin to what happens to be installed.
- **`copier` is not installed** → `uv tool install copier` (needs uv working
  first).

`golangci-lint`, `gofumpt`, `ruff`, and `mypy` are intentionally *not*
installed globally — they become version-pinned dev dependencies of each
generated service, installed by `go tool` / `uv` respectively.

## Do

1. Fix `uv` and install `copier` per "Starting state" above. Then extend
   root `.tool-versions` to also pin `golang` and `python` — mint's own
   `make verify` builds generated services, so mint's toolchain needs to be
   as reproducible as theirs. Use the versions settled in chunk 01 if this
   chunk runs after it; otherwise pin what's installed and let chunk 01
   revise.

   > **Revised by ADR 0011.** This chunk is done and it pinned `golang
   > 1.26.5` / `python 3.14.6` — what was installed at the time. ADR 0011
   > settled the real pins as `golang 1.26.6` / `python 3.14.7` / `uv
   > 0.12.5`; both bumps are security releases and both are asdf-installable.
   > **Chunk 02 applies them** (`asdf install` first) — do not treat the
   > current `.tool-versions` as authoritative.
2. Create the directory skeleton from spec § Repo layout: `templates/`
   (with `_common/`, `go-service/`, `python-service/`), `docs/` (with
   `decisions/`), `scripts/`, `tasks/`.
3. Write `.gitignore` for the mint repo itself: temp dirs used by the verify
   harness, `.venv`, editor cruft, and `.claude/settings.local.json` (local
   agent settings, already present and untracked — it should stay that way).
4. Write the mint repo's own `Makefile` with `help` implemented (parse `##`
   comments) and stubs that exit 1 with "not implemented yet" for `parity`,
   `verify`, `test`, `lint`, `fmt`. Later chunks fill these in.
5. Write `AGENTS.md` for the mint repo — at this stage a short orientation:
   what Mint is, the two governing principles from the spec, where the spec
   lives, and a pointer to `tasks/`. Symlink `CLAUDE.md` → `AGENTS.md`.
6. Write `README.md` as a stub: what Mint is, what state it's in, and a link
   to the spec. It gets filled in properly in chunk 10.
7. Create `docs/decisions/0000-template.md` — an ADR template with
   context / decision / consequences / status headings, and a one-paragraph
   note in `docs/decisions/README.md` on when to write one.
8. Create empty-but-headed `docs/architecture.md`, `docs/logging.md`,
   `docs/config.md`, `docs/agents.md`, `docs/testing.md`. Each gets a
   one-line "source of truth for X; filled in by chunk NN" note so nobody
   mistakes an empty file for a missing one.
9. Create `CHANGELOG.md` with an Unreleased section.
10. Initial commit.

## Out of scope

Anything under `templates/` beyond the empty directories. No `copier.yml`,
no service code, no ADR content (chunk 01 writes those).

## Deliverables

- Initialized git repo on `main`, one commit
- Directory skeleton matching spec § Repo layout
- `Makefile` where `make help` works and lists every planned target
- `AGENTS.md` + `CLAUDE.md` symlink, `README.md` stub, `CHANGELOG.md`
- ADR template and the five empty-but-headed `docs/` files

## Acceptance criteria

- `make help` lists mint's own targets with descriptions. (These are *not*
  the generated-service targets in spec § Makefile parity — that's a
  different list, delivered by chunk 02.)
- Every unimplemented target exits non-zero with a message naming the chunk
  that implements it — never a bare make error, and never a silent success
  that could be mistaken for a passing check.
- `git log` shows one commit on `main`; `git status` is clean, with
  `.claude/settings.local.json` ignored rather than committed.
- `prompt.md` and `tasks/` are tracked in that first commit — they predate
  it and must not be left untracked.
- `asdf which uv`, `uv --version`, and `copier --version` all resolve.
- `readlink CLAUDE.md` returns `AGENTS.md`.

## Flag back before finishing

If `uv 0.12.5` can't be installed by asdf, say so rather than editing the
pin down to an installed version or reaching for a shell alias. Every
generated service depends on asdf resolving a pinned version cleanly, so a
workaround here is a bug that ships to every service later.
