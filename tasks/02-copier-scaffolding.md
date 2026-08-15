# 02 — Copier scaffolding + harness skeleton

**Spec:** § Copier mechanics, § Generated service layout, § Makefile parity,
§ Parity enforcement, § asdf + direnv
**Depends on:** 01. **ADRs 0009 (layout + versioning) and 0011 (pins) are
binding here**; 0004, 0006, 0007, 0008 and 0010 each add a concrete
requirement to this chunk.
**Size:** L — the largest early chunk
**Standing rules:** [tasks/README.md](README.md#standing-rules--these-apply-to-every-chunk)

> **Human checkpoint after this chunk.** Everything else is built on this
> layout. Fixing delimiters, the question set, or the directory shape later
> means touching every template file that exists by then.

> **The layout in spec § "Repo layout" is wrong and ADR 0009 replaces it.**
> Two per-template `copier.yml` files **do not work**: Copier's `get_repo()`
> only treats a path as VCS-tracked when it `is_git_repo_root`, so pointing
> `copier copy` at `templates/go-service/` produces a service with **no
> `_commit` at all** — no mint mark, and `copier update` exits 1 permanently.
> Read ADR 0009 Findings 4 and 5 before you write a line of YAML.

## Goal

`copier copy . <tmp> -d language=go` and `-d language=python`, run from the
**mint repo root**, each produce a service that builds, boots, and answers an
HTTP request — plus the first working version of the parity and verify
harnesses.

The generated service is deliberately almost empty at this stage. It has the
full directory skeleton, a real Makefile, real tooling config, and a
main that starts an HTTP server returning `200 ok` on `/`. Config, logging,
errors, health, and routing all arrive in later chunks and drop into the
directories this chunk creates.

## Do

1. **Apply ADR 0011's pins first.** `asdf install golang 1.26.6` and `asdf
   install python 3.14.7`, then update the repo root `.tool-versions` to
   `golang 1.26.6` / `python 3.14.7` / `uv 0.12.5`. Chunk 00 pinned what was
   installed at the time; these are the settled values and both bumps are
   security releases. Everything below is built and verified on them.

2. **`templates/_common/`** — the genuinely language-agnostic files: the
   `docs/` tree that gets copied into every service, `.gitignore.jinja`, the
   AGENTS.md skeleton, the shared sections of the README.

   **Both templates reach it by relative symlink**, per ADR 0009 decision 3 —
   e.g. `templates/go-service/template/docs -> ../../_common/docs`. Copier's
   `preserve_symlinks` defaults to `False`, so the *content* lands in the
   generated service as a real file, not a dangling link. Leave that default
   alone. Verified in the ADR 0009 spike; assert it in the verify script
   (`test ! -L <generated>/docs/…`).

3. **One `copier.yml`, at the git repo root.** Not two, not in
   `templates/*/`. Structure, per ADR 0009 decision 2 and Finding 5:

   ```yaml
   ---
   _subdirectory: "templates/[[ language ]]-service/template"
   _min_copier_version: "9.17.1"
   language:
     type: str
     choices: {Go: go, Python: python}
     default: go
   ---
   !include "questions-shared.yml"
   ---
   module_path:
     when: "[[ language == 'go' ]]"
   package_name:
     when: "[[ language == 'python' ]]"
   ```

   Four things about this that the spike had to discover:

   - `_subdirectory` is Jinja-rendered before use, which is what makes one
     `copier.yml` serve two templates.
   - `!include` **must be its own YAML document.** Used as a mapping entry it
     fails with `InvalidConfigFileError … could not find expected ':'`.
   - `language` is a recorded answer in `.copier-answers.yml`. It must never
     be re-asked on update, and **no generated file may branch on it** beyond
     selecting the subdirectory. The spec's warning against
     `[% if language == "go" %]` is now load-bearing: with one question set
     there is nothing else keeping the two trees honest.
   - `templates/<lang>-service/` keeps only its `template/` tree. There is no
     per-template `copier.yml` and no per-template `CHANGELOG.md`.

4. **The question set** — the spec's seven questions plus `language`, in one
   shared document, same order for both languages by construction. Every
   question gets a `help` string, a default where derivable, and a validator
   where a bad answer would produce code that doesn't compile: `service_name`
   regex, `port`/`admin_port` range, `module_path`/`package_name` format.
   Only `module_path` and `package_name` carry a `when:`, and it is gated on
   `language` and nothing else.

   `admin_port`, per ADR 0008's Consequences, needs three things the spec's
   range check alone doesn't cover:

   - it must be in 1024–65535 and **may equal `port`** — that is the
     documented collapse path, not an error;
   - the derived default `port + 1000` is invalid when `port > 64535`, so the
     default expression must clamp or the validator must reject it with a
     message that says so. Bad input fails at prompt time, and this is the one
     case where the *default* can be the bad input;
   - the help text states the collapse behaviour and states that the admin
     port is **not a security boundary** — the same sentence as
     `docs/architecture.md`, so the reason travels with the question.

   `service_name`'s validator (`^[a-z][a-z0-9-]{1,38}[a-z0-9]$`) is also what
   guarantees the derived Prometheus metric namespace is always a legal
   metric-name prefix (ADR 0003 § 3). Don't weaken it.

5. **Jinja delimiters** — override to `[[ ]]` / `[% %]` / `[# #]`. Do this
   now; there are no template files yet to migrate. Note that
   `_subdirectory` and the two `when:` expressions use these delimiters too.

6. **`_tasks`** — `git init`, then `go mod tidy` / `uv sync`, then a printed
   next-steps block ending with `direnv allow` and `make run`. A minted
   service must need zero manual repair. (Chunk 09 adds `make agents-docs` to
   `_tasks`, because ADR 0007 requires `openapi.json` and `llms.txt` to come
   into existence at generation time rather than ship as template files.
   Leave the seam; don't build it.)

7. **The generated skeleton**, per spec § Generated service layout: every
   directory present with a package-level doc comment / `__init__.py`
   stating what belongs there and what does not. Empty directories that
   explain themselves are the point — they're what makes an agent put code
   in the right place in chunk 03 onward.

   Two structural requirements from ADR 0004 that must be right from the
   first commit, because they are expensive to retrofit:

   - `internal/transport/http/` is nested **one level deeper than it needs to
     be**, so a second transport is a peer directory rather than a refactor.
     Its doc comment says so.
   - Nothing outside `internal/transport/http/` may import `net/http` or
     FastAPI request types. Chunk 07 wires the lint check; this chunk creates
     the directory shape that makes it meaningful.

   The Python entrypoint is `src/<pkg>/__main__.py` (ADR 0010 § 6), mirroring
   Go's single `cmd/<service>/main.go`.

8. **Both Makefiles** — every target from the spec's parity table, with
   `help`, `fmt`, `lint`, `build`, `run`, `clean` genuinely working and the
   rest exiting non-zero with "not implemented yet." Same target names, same
   `##` descriptions, same output style.

   **`make run` invokes `python -m <pkg>`, never the `uvicorn` CLI** (ADR
   0010 § 6). The CLI installs its own non-propagating log handlers *before*
   the app module is imported, so no amount of in-app configuration can
   reclaim them, and the service ships two log formats. This is a constraint
   on the Makefile now even though logging lands in chunk 04.

9. **Tooling config**, all pins from ADR 0011's table:

   - `.tool-versions` in the generated service: `golang 1.26.6` /
     `python 3.14.7` / `uv 0.12.5`.
   - Go: `go 1.26.6` in `go.mod`; linters pinned by `tool` directives
     (`go get -tool mvdan.cc/gofumpt@v0.11.0`,
     `…/golangci-lint@v2.12.2`) rather than asdf entries or
     `go install …@version` in the Makefile — a shared `GOBIN` is exactly the
     non-reproducibility the pinning exists to remove. Expect ~212
     `// indirect` requires from golangci-lint; that is accepted, and the
     generated README must justify it (chunk 10).
   - `.golangci.yml` **starts with `version: "2"`.** golangci-lint 2.x treats
     a v1-shaped config as a hard error, not a warning.
   - `pyproject.toml` with `requires-python == "3.14.*"`, an **explicit
     `[tool.ruff.lint] select`** — never ruff's defaults, which went from 59
     rules to 413 in 0.16.0 — mypy config, and `uv.lock` committed.
   - The Python test-client dependency is **`httpx2`, not `httpx`**.
     Starlette 1.6.0 emits a `StarletteDeprecationWarning` from
     `fastapi.testclient` otherwise, in every generated service on day one.
   - `opentelemetry-instrumentation-fastapi` pins to `0.65b0` — a beta
     version string, normal for the OTel contrib line. Anything that filters
     prereleases has to be told to allow it.
   - `.envrc` for direnv that works with a single `direnv allow`. It may use
     `dotenv_if_exists .env` — per ADR 0006 that is *the* supported way to
     keep uncommitted local overrides, because the values arrive as ordinary
     environment variables before either process starts. `.env` and
     `config/config.local.yaml` are both gitignored.

10. **`.gitattributes` in the generated service** carrying `openapi.json
    -merge` and `llms.txt -merge`, per ADR 0007 decision 3. A branch-merge
    conflict then leaves a *valid* file in the worktree instead of a JSON
    document with conflict markers in it, and the documented resolution is
    one line: *resolve the conflict in the registry, then run `make
    agents-docs`.* The files themselves don't exist yet — that is the point.

    **The templates must never contain `openapi.json` or `llms.txt`**, not
    even empty placeholders, not even as `.jinja` files. Copier three-way-
    merges only files it renders; the moment either becomes a template file,
    every `copier update` conflicts on it forever. Assert this in
    `scripts/parity.sh` rather than remembering it.

11. **`scripts/parity.sh`** — the first three checks from spec § Parity
    enforcement, with check #1 changed in shape by ADR 0009:

    - **#1 is now an assertion over one question set, not a diff of two.**
      There is only one `copier.yml`, so there is nothing to diff. Assert
      instead: every question except `module_path` and `package_name` is
      unconditional, and those two are `when:`-gated on `language` and
      nothing else. This is structurally stronger — the questions can no
      longer drift, because there is one of them.
    - #2: generate both from **one** fixture answers file, with `language`
      supplied on the command line. The fixture carries both `module_path`
      and `package_name`; the `when:` gates discard the irrelevant one. That
      one file generating both trees is the check.
    - #3: diff the normalized directory trees.
    - Plus the ADR 0007 assertion from item 10.

    Wire to `make parity`. Commit the fixture answers file.

12. **`scripts/verify-template.sh`** — minimal version: generate both from
    the repo root, build both, boot both, curl `/`, assert 200, tear down.
    Wire to `make verify`.

13. **Mint mark** in the generated README, per ADR 0009 decision 7: read the
    version from `.copier-answers.yml`'s `_commit` and the template name from
    the **`language` answer**, not from the tag — ``Minted from `go-service`
    @ `v1.2.0`.`` Omit the line entirely when `_commit` is unset. Tags are
    plain repo-wide semver; there is no `go-service/…` tag and never will be.

    The generated README must also say that the version is repo-wide, so a Go
    service's mint mark can advance on a Python-only release and
    `CHANGELOG.md` is the only place that says whether a release contained
    anything for it (ADR 0009 Consequences).

## Out of scope

Config loading, logging, error handling, health endpoints, routing beyond
the single `/` probe, tracing, metrics, the operation registry, tests beyond
what proves the skeleton boots. All of that has its own chunk.

Do not create `openapi.json` or `llms.txt` in the templates — see item 10.
Do not tag anything; chunk 10 cuts `v0.1.0`.

## Deliverables

- Root `copier.yml` (+ the `!include`-ed shared question document),
  `templates/_common/`, `templates/go-service/template/`,
  `templates/python-service/template/`, with `_common/` symlinked into both
- Working `make parity` (3 checks + the no-artifact-in-template assertion)
  and `make verify` (generate/build/boot)
- A committed fixture answers file used by both
- Repo root `.tool-versions` bumped to ADR 0011's pins

## Acceptance criteria

- `copier copy . <tmp> -d language=go` with the fixture answers, **run from
  the mint repo root**, produces a service where `make build && make run`
  works and `curl localhost:<port>/` returns 200, with no manual repair
  between generation and run.
- Same for `-d language=python`, and `make run` there shells out to
  `python -m <pkg>`, not `uvicorn`.
- The generated `.copier-answers.yml` contains a `_commit`, and
  `<generated>/docs/` holds real files, not symlinks.
- `copier update` in a generated service runs without erroring on a missing
  template reference. (It has nothing to update to until chunk 10 tags
  `v0.1.0` — but it must not fail the way the ADR 0009 Finding 4 layout does.)
- `make help` output from the two generated services is identical except for
  the service name.
- `make parity` passes.
- `make parity` **fails** if you add a `when:` to a question that shouldn't
  have one, or make `module_path` unconditional. Demonstrate this, then
  revert. (The old "add a question to one `copier.yml` and not the other"
  demonstration is no longer possible — that is the point of the change.)
- `make parity` **fails** if you add an `openapi.json` to either template
  tree. Demonstrate, then revert.
- `make verify` passes.
- Bad input is rejected at prompt time: `service_name=Foo_Bar`, `port=80`,
  and an empty `service_owner` are all refused by copier before generation.
  `admin_port == port` is **accepted**.
- `port=65000` either clamps the derived `admin_port` default or is rejected
  with a message naming the problem — it does not generate a service that
  fails to bind at boot.
- No `{{ }}` remains in any template file — delimiters are `[[ ]]`.
- No generated file branches on `language`. Grep for it.
- `.golangci.yml` passes `go tool golangci-lint config verify`; `ruff` runs
  against an explicit `select` list, not its defaults.

## Flag back before finishing

- Any place the two generated trees genuinely can't be made parallel, and
  what normalization `parity.sh` had to do to compare them.
- Whether `_tasks` running `git init` inside a generated service conflicts
  with how developers will actually create these repos.
- If `uv sync` in `_tasks` is slow enough to hurt the generation experience,
  say so — it may belong in the printed next-steps instead.
- Whether the `!include` document and the `when:`-gated tail read clearly
  enough that someone adding a question will put it in the shared document
  rather than in the gated one. That mistake would reintroduce exactly the
  drift ADR 0009 removed, and nothing but review catches it.

*Settled, do not re-open:* the single-`copier.yml` layout, the
`language` question, plain repo-wide semver tags, and parity check #1's
change of shape are all ADR 0009, approved. The port split and its collapse
path are ADR 0008, approved. The pins are ADR 0011, approved.
