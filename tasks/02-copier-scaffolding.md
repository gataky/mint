# 02 — Copier scaffolding + harness skeleton

**Spec:** § Copier mechanics, § Generated service layout, § Makefile parity,
§ Parity enforcement, § asdf + direnv
**Depends on:** 01 (needs the pinned versions and ADR 0008's port decision)
**Size:** L — the largest early chunk
**Standing rules:** [tasks/README.md](README.md#standing-rules--these-apply-to-every-chunk)

> **Human checkpoint after this chunk.** Everything else is built on this
> layout. Fixing delimiters, the question set, or the directory shape later
> means touching every template file that exists by then.

## Goal

`copier copy templates/go-service/ /tmp/foo` and the Python equivalent each
produce a service that builds, boots, and answers an HTTP request — plus the
first working version of the parity and verify harnesses.

The generated service is deliberately almost empty at this stage. It has the
full directory skeleton, a real Makefile, real tooling config, and a
main that starts an HTTP server returning `200 ok` on `/`. Config, logging,
errors, health, and routing all arrive in later chunks and drop into the
directories this chunk creates.

## Do

1. **`templates/_common/`** — the genuinely language-agnostic files: the
   `docs/` tree that gets copied into every service, `.gitignore.jinja`, the
   AGENTS.md skeleton, the shared sections of the README. Both templates
   pull it in.

2. **Both `copier.yml` files** — identical question set, same order, per the
   table in spec § Copier mechanics. Every question gets a `help` string, a
   default where derivable, and a validator where a bad answer would produce
   code that doesn't compile: `service_name` regex, `port`/`admin_port`
   range, `module_path`/`package_name` format.

3. **Jinja delimiters** — override to `[[ ]]` / `[% %]` / `[# #]` in both.
   Do this now; there are no template files yet to migrate.

4. `_min_copier_version` and `_subdirectory: template` set explicitly in
   both.

5. **`_tasks`** — `git init`, then `go mod tidy` / `uv sync`, then a printed
   next-steps block ending with `direnv allow` and `make run`. A minted
   service must need zero manual repair.

6. **The generated skeleton**, per spec § Generated service layout: every
   directory present with a package-level doc comment / `__init__.py`
   stating what belongs there and what does not. Empty directories that
   explain themselves are the point — they're what makes an agent put code
   in the right place in chunk 03 onward.

7. **Both Makefiles** — every target from the spec's parity table, with
   `help`, `fmt`, `lint`, `build`, `run`, `clean` genuinely working and the
   rest exiting non-zero with "not implemented yet." Same target names, same
   `##` descriptions, same output style.

8. **Tooling config**: `.tool-versions` with the versions pinned in chunk
   01; `golangci-lint` config and `go.mod`; `pyproject.toml` with ruff and
   mypy config, `uv.lock` committed; `.envrc` for direnv that works with a
   single `direnv allow`.

9. **`scripts/parity.sh`** — first three checks from spec § Parity
   enforcement: diff the two question sets; generate both from one fixture
   answers file; diff the normalized directory trees. Wire to `make parity`.
   Include the fixture answers file in the repo.

10. **`scripts/verify-template.sh`** — minimal version: generate both, build
    both, boot both, curl `/`, assert 200, tear down. Wire to `make verify`.

11. **Mint mark** in the generated README, read from `.copier-answers.yml`'s
    `_commit`, degrading gracefully (omit the line entirely) when the
    template repo has no tags.

## Out of scope

Config loading, logging, error handling, health endpoints, routing beyond
the single `/` probe, tracing, metrics, the operation registry, tests beyond
what proves the skeleton boots. All of that has its own chunk.

## Deliverables

- `templates/_common/`, `templates/go-service/`, `templates/python-service/`
- Working `make parity` (3 checks) and `make verify` (generate/build/boot)
- A committed fixture answers file used by both

## Acceptance criteria

- `copier copy templates/go-service/ <tmp>` with the fixture answers
  produces a service where `make build && make run` works and `curl
  localhost:<port>/` returns 200, with no manual repair between generation
  and run.
- Same for `templates/python-service/`.
- `make help` output from the two generated services is identical except for
  the service name.
- `make parity` passes.
- `make parity` **fails** if you add a question to one `copier.yml` and not
  the other. Demonstrate this, then revert.
- `make verify` passes.
- Bad input is rejected at prompt time: `service_name=Foo_Bar`, `port=80`,
  and an empty `service_owner` are all refused by copier before generation.
- No `{{ }}` remains in any template file — delimiters are `[[ ]]`.

## Flag back before finishing

- Any place the two generated trees genuinely can't be made parallel, and
  what normalization `parity.sh` had to do to compare them.
- Whether `_tasks` running `git init` inside a generated service conflicts
  with how developers will actually create these repos.
- If `uv sync` in `_tasks` is slow enough to hurt the generation experience,
  say so — it may belong in the printed next-steps instead.
