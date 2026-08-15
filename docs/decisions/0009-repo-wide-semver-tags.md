# 0009 — Tag the mint repo with plain repo-wide semver, not per-template tags

**Status:** accepted (2026-08-14)
**Date:** 2026-08-14
**Chunk:** [01 — Decisions and ADRs](../../tasks/01-decisions.md)

## Context

`prompt.md` § "Copier mechanics" proposes tagging templates independently —
`go-service/v1.2.0` and `python-service/v1.2.0` — "so a Python-only fix
doesn't bump the mint mark on every Go service." § "Mint mark" then relies on
Copier's `_commit` field to render "Minted from `go-service` @ `v1.2.0`."

Those two requirements are in tension, because Copier resolves template
versions through PEP 440. This was spiked end to end with copier 9.17.1,
git 2.55.0, uv 0.12.5, in
`/private/tmp/.../scratchpad/adr-0009/` (throwaway, never in the repo).

### The mechanism, from Copier's source

Copier picks a ref by listing every tag and discarding the ones that are not
PEP 440 versions — `copier/_vcs.py:186-191`:

```python
all_tags = (tag for tag in all_tags if valid_version(tag))
if not use_prereleases:
    all_tags = (tag for tag in all_tags if not version.parse(tag).is_prerelease)
sorted_tags = sorted(all_tags, key=version.parse, reverse=True)
```

`Template.version` (`copier/_template.py:634-659`) parses `git describe
--tags --always` through dunamai and then `packaging.version.Version`,
returning `None` if neither parses. `run_update` (`_main.py:1335-1344`) hard
-requires both versions to be non-`None` and comparable.

Parsing every candidate tag scheme against `packaging`:

```
  'go-service/v1.2.0'        -> INVALID (copier discards this tag)
  'python-service/v1.2.0'    -> INVALID (copier discards this tag)
  'go-service-v1.2.0'        -> INVALID (copier discards this tag)
  'go/1.2.0'                 -> INVALID (copier discards this tag)
  'v1.2.0'                   -> PARSES as 1.2.0
  'v1.2.0+go'                -> PARSES as 1.2.0+go
  '1!1.2.0'                  -> PARSES as 1!1.2.0
  'go1.2.0'                  -> INVALID (copier discards this tag)
  '1.2.0-go'                 -> INVALID (copier discards this tag)
```

### Finding 1 — slash tags do not fail loudly, they fail silently

A single-template repo at the git root, tagged `go-service/v0.1.0`:

```
$ git tag -l
go-service/v0.1.0
$ copier copy --defaults --trust ./slashrepo ./out-c
No git tags found in template; using HEAD as ref

Copying from template version 0.0.0.post1.dev0+d05dda8
    create  README.md
    create  .copier-answers.yml
    create  main.go
```

The tag was discarded ("No git tags found"), yet `.copier-answers.yml` looks
correct, because `_commit` is `git describe --tags --always` and HEAD happened
to sit on the tag:

```yaml
_commit: go-service/v0.1.0
_src_path: /…/slashrepo
port: 8080
service_name: my-service
```

and the mint mark renders perfectly:

```
# my-service
Minted from `go-service` @ `go-service/v0.1.0`.
```

**This is the trap.** Generation looks like it works. Nothing is actually
pinned.

### Finding 2 — with slash tags, `copier update` tracks HEAD, and unreleased work leaks

Tag `go-service/v0.2.0`, then push one further *untagged* WIP commit adding
`BROKEN-WIP.txt.jinja`:

```
$ git tag -l
go-service/v0.1.0 go-service/v0.2.0
$ git describe --tags --always
go-service/v0.2.0-1-g02a91d4

$ copier update --defaults --trust     # in the generated service
No git tags found in template; using HEAD as ref
Updating to template version 0.0.0.post3.dev0+02a91d4

$ ls
.copier-answers.yml  BROKEN-WIP.txt  Makefile  README.md  main.go
```

`BROKEN-WIP.txt` — an unreleased, untagged template commit — is now in the
service. The mint mark degrades to a non-version:

```
Minted from `go-service` @ `go-service/v0.2.0-1-g02a91d4`.
```

`copier check-update` is also silently wrong, because it compares HEAD to
HEAD:

```
$ copier check-update
No git tags found in template; using HEAD as ref
Project is up-to-date!
```

`--vcs-ref go-service/v0.1.0` *does* check out (it is a valid git ref), but
`Template.version` is still `0.0.0.post1.dev0+d05dda8`, so it buys nothing.

### Finding 3 — no tag scheme isolates two templates in one repo

The only parseable "label" form is a PEP 440 local version. Copier does not
filter on it; `get_latest_version` sorts *all* valid tags together and takes
the global maximum. Tagging `v1.0.0+go` and a later python-only commit
`v1.1.0+python`, then minting a **Go** service:

```
$ copier copy --defaults --trust -d language=go ./localver ./out-lv
Copying from template version 1.1.0

$ cat out-lv/.copier-answers.yml
_commit: v1.1.0+python
language: go
service_name: my-service
```

A Go service whose mint mark reads `v1.1.0+python`. Per-template isolation
inside one repo is not achievable by naming tags.

### Finding 4 — the proposed repo layout breaks git detection entirely

Independent of tags: `copier.yml` must sit at the **git repo root**.
`get_repo()` (`_vcs.py:82-155`) only treats a path as a template-with-history
if it `is_git_repo_root`. Pointing Copier at `templates/go-service/` as
§ "Repo layout" proposes:

```
$ copier copy --defaults --trust ./mint-spike/templates/go-service ./out-a
Copying from template version None
    create  README.md
    create  .copier-answers.yml
    create  main.go

$ cat out-a/.copier-answers.yml
_src_path: /…/mint-spike/templates/go-service
port: 8080
service_name: my-service          # <- no _commit at all
```

No `_commit` means no mint mark *and* no updates ever:

```
$ copier update --defaults --trust
Cannot update because cannot obtain old template references from `.copier-answers.yml`.
exit 1
```

This is the load-bearing finding. It kills two-`copier.yml`-in-subdirectories
regardless of the tagging question.

### Finding 5 — one root `copier.yml` with a rendered `_subdirectory` works

`_subdirectory` is Jinja-rendered before use (`_main.py:1237`,
`subdir = self._render_string(self.template.subdirectory)`), and `copier.yml`
supports multi-document YAML with `!include`. Both verified:

```yaml
---
_subdirectory: "templates/[[ language ]]-service/template"
language: {type: str, choices: {Go: go, Python: python}, default: go}
---
!include "questions-shared.yml"
---
module_path:
  when: "[[ language == 'go' ]]"
package_name:
  when: "[[ language == 'python' ]]"
```

```
$ copier copy --defaults --trust -d language=go ./inc ./out-inc-go
Copying from template version 1.0.0
    create  go.mod
    create  .copier-answers.yml
$ cat out-inc-go/.copier-answers.yml
_commit: v1.0.0
language: go
module_path: github.com/org/my-service
port: 8080
service_name: my-service

$ copier copy --defaults --trust -d language=python ./inc ./out-inc-py
Copying from template version 1.0.0
$ cat out-inc-py/.copier-answers.yml
_commit: v1.0.0
language: python
package_name: my_service
port: 8080
service_name: my-service
```

(`!include` must be its own YAML document — used as a mapping entry it fails
with `InvalidConfigFileError … could not find expected ':'`.)

`templates/_common/` reaches both templates through a relative symlink
(`templates/go-service/template/docs -> ../../_common/docs`); Copier's
`preserve_symlinks` defaults to `False` (`_template.py:553-558`), so the
*content* lands in the service as a real file, not a dangling link:

```
$ find . -not -path "./.git/*"
./.copier-answers.yml  ./docs  ./docs/overview.md  ./main.go  ./README.md
$ ls -l docs/overview.md
.rw-r--r--@ 20 …  overview.md        # real file, not a symlink
```

### Finding 6 — plain semver behaves exactly as the spec wants

Same template, tags `v0.1.0`/`v0.2.0`:

```
$ copier copy --defaults --trust ./semverrepo ./out-e
Copying from template version 0.2.0
$ grep _commit out-e/.copier-answers.yml
_commit: v0.2.0
```

Pinned to `v0.1.0`, with an untagged WIP commit sitting on the template's
`main`, `copier update` correctly stops at the last tag and holds the
unreleased work back:

```
$ copier update --defaults --trust
Updating to template version 0.2.0
WIP leaked?
NO - untagged work correctly held back
files: main.go  Makefile  README.md
```

Conflicts are ordinary git conflicts — no `.rej` files, no bespoke format:

```
$ copier update --defaults --trust
Updating to template version 0.3.0
$ git status --short
 M .copier-answers.yml
 M README.md
UU main.go
$ cat main.go
package main
<<<<<<< before updating
// revision TWO - added a comment and a helper
func helper() string { return "my-service" }
func main() {
	// LOCAL EDIT BY THE SERVICE TEAM
	println(helper(), 9090)
}
=======
// revision THREE - upstream changed the same lines
func helper() string { return "my-service v3" }
func main() { println(helper(), 8080, "upstream") }
>>>>>>> after updating
```

### Finding 7 — the measured cost of *not* slash-tagging is two lines

The whole premise of per-template tags is that a Python-only fix shouldn't
churn Go services. Measured: two templates in one repo, python-only change,
repo-wide tag `v1.1.0`, then `copier update` in an existing **Go** service:

```
$ copier update --defaults --trust
Updating to template version 1.1.0
$ git diff --stat
 .copier-answers.yml | 2 +-
 README.md           | 2 +-
 2 files changed, 2 insertions(+), 2 deletions(-)

-_commit: v1.0.0
+_commit: v1.1.0
-Minted from `go-service` @ `v1.0.0`.
+Minted from `go-service` @ `v1.1.0`.
```

Zero code churn, zero conflict risk — both changed lines are Copier-owned.
And `copier update` is opt-in; nothing forces the Go service to run it.

The one real cost is advisory noise. A Go service asked about a python-only
release reports an update that contains nothing for it:

```
$ copier check-update --output-format json
{"update_available": true, "current_version": "1.3.0", "latest_version": "1.4.0"}
```

A `templates/_common/`-only change, tagged `v1.3.0`, correctly reaches both:

```
--- out-go ---   Updating to template version 1.3.0
 .copier-answers.yml | 2 +-   README.md | 2 +-   docs/overview.md | 2 +-
--- out-py ---   Updating to template version 1.3.0
 .copier-answers.yml | 2 +-   README.md | 2 +-   docs/overview.md | 2 +-
```

## Decision

1. **Tag the mint repo with plain repo-wide semver: `v<MAJOR>.<MINOR>.<PATCH>`.**
   One version line covers both templates. No slashes, no prefixes, no PEP 440
   local-version labels. A tag that `packaging.version.Version()` cannot parse
   is a release-process bug.
2. **One `copier.yml` at the git repo root**, with
   `_subdirectory: "templates/[[ language ]]-service/template"`, a `language`
   question (`{Go: go, Python: python}`), the shared questions in a
   `!include`-ed document, and only `module_path` / `package_name` gated by
   `when:`. The per-template `templates/<lang>-service/copier.yml` files in
   spec § "Repo layout" do not exist; each template directory keeps only its
   `template/` tree.
3. **`templates/_common/` is wired into each template by relative symlink**
   (`templates/<lang>-service/template/docs -> ../../_common/docs`), and
   `preserve_symlinks` stays at its default `False`.
4. **A `templates/_common/` change bumps the single repo version**, at the
   semver level its effect on a *generated service* warrants — not at a level
   chosen from which directory changed. It reaches both languages by
   construction; there is no version in which it reaches only one.
5. **Semver level is judged by the generated service, not the template repo.**
   - **MAJOR** — a change existing services cannot absorb by merge alone:
     removing or renaming a Copier question, renaming a generated directory,
     renaming a config key or env var, changing the error-body contract or the
     reserved log field set. Every MAJOR needs a `_migrations` entry.
   - **MINOR** — additive: a new question with a default, a new file, a new
     Makefile target, a new middleware in a reserved slot.
   - **PATCH** — fixes and pinned-toolchain bumps that change no interface.
6. **Scope lives in `CHANGELOG.md`, not in the tag.** One `CHANGELOG.md` at
   the repo root, entries scoped `go-service:` / `python-service:` /
   `common:`, so a reader can tell at a glance whether `v1.4.0` contains
   anything for their language. Replacing spec § "Versioning"'s "keep
   `CHANGELOG.md` per template."
7. **The mint mark takes the template name from the `language` answer, not
   from the tag**: ``Minted from `go-service` @ `v1.2.0`.``, rendered only
   when `_copier_answers._commit` is set, omitted entirely otherwise (spec
   § "Mint mark" already requires the graceful degradation).

## Alternatives considered

**Per-template slash tags (`go-service/v1.2.0`), as the spec proposes.**
Rejected: Copier discards them as non-PEP-440 (Finding 1), so ref resolution
silently falls back to HEAD. The observed result is unreleased template
commits landing in production services (Finding 2), a mint mark that reads
`go-service/v0.2.0-1-g02a91d4`, and a `copier check-update` that always
answers "up-to-date". The failure is quiet, which is worse than loud — it
would have surfaced months after chunk 02, in someone else's service.

**PEP 440 local-version labels (`v1.2.0+go`, `v1.3.0+python`).** The only
scheme that both parses and *looks* namespaced. Rejected: Copier does no
label filtering — it sorts all tags into one ordering and takes the maximum,
so a Go service resolves to `v1.1.0+python` (Finding 3). It reintroduces the
same silent-wrongness as slash tags while looking more legitimate.

**PEP 440 epochs (`1!1.2.0` for Go, `2!1.2.0` for Python).** Parses, and
epochs dominate the sort, so one language would permanently win every
resolution. Strictly worse than local versions.

**Separate git repos per template (`mint-go-service`, `mint-python-service`).**
The only design that genuinely isolates versions, and it works — Finding 6 is
exactly this shape. Rejected on cost, not on mechanics: it ends the monorepo
that spec § "Repo layout" and § "Parity enforcement" are built on.
`make parity` diffs two generated trees, two `make help` outputs and two
`/openapi.json`s from one checkout; across two repos that becomes a
cross-repo CI job with a floating "which commit of the other repo?" question.
`templates/_common/` would have to become a submodule, a subtree, or a
duplicated tree — and a duplicated tree is precisely the drift the spec's
first principle exists to prevent. Revisit only if the `check-update` noise
in Finding 7 turns out to matter more than parity does.

**Keep two `copier.yml` files in `templates/<lang>-service/` and accept
whatever versioning falls out.** Rejected: Finding 4 — Copier does not treat a
non-repo-root path as VCS-tracked at all, so those services get no `_commit`,
no mint mark, and `copier update` exits 1 permanently. This is not a
versioning tradeoff; it is a broken layout.

**Hand-write the version into the generated README instead of using
`_commit`.** Rejected by spec principle 1 — a second authoring location that
drifts. It is also unnecessary once tags parse.

## Consequences

**Easy.** `copier update` and `copier check-update` behave as documented.
Version pinning is real: untagged work on `main` cannot reach a service
(Finding 6). One tag, one changelog, one release decision. The
`templates/_common/` question answers itself — there is only one version to
bump. Generating from a local checkout, a GitHub URL or `--vcs-ref v1.2.0`
all behave identically.

**Hard, and named honestly:**

- **A Go service's mint mark advances on python-only releases.** Measured at
  two lines with no conflict risk (Finding 7), but the version number alone
  stops meaning "something changed for me" — `CHANGELOG.md` is the only place
  that answers that. Every generated README must say so.
- **`copier check-update` produces false positives.** A Go service will be
  told `{"update_available": true}` for a release containing only Python
  changes. If this becomes a nuisance, the fix is a scope-aware wrapper in
  `scripts/` that reads the changelog — not a change to the tag scheme.
- **`make parity` check #1 changes shape.** Spec § "Parity enforcement" says
  "diff the two `copier.yml` question sets"; there is now one set, so there is
  nothing to diff. The check becomes an assertion instead: every question
  except `module_path` and `package_name` is unconditional, and those two are
  `when:`-gated on `language` and nothing else. This is structurally stronger
  than diffing two files — the questions can no longer drift, because there is
  one of them — but it *is* a deviation from the spec and needs sign-off
  before chunk 02.
- **`language` becomes a Copier answer, recorded in `.copier-answers.yml`.**
  It must never be re-asked on update, and no generated file may branch on it
  beyond selecting the subdirectory. Spec § "Repo layout" warns against
  `[% if language == "go" %]`; that warning is now load-bearing.
- **Cosmetic:** `copier update` prints
  `Make sure Git >= 2.24 is installed to improve updates.` under git 2.55.0.
  It is a fallback path in `_main.py:1520-1531` when a `git diff
  --inter-hunk-context=-1` invocation fails, not a real version problem —
  ignore it, and don't let it end up in the generated README's troubleshooting
  section as advice.

**To reverse this** (move to per-template versions), split the repo in two,
give each plain semver tags, resolve `templates/_common/` into a submodule or
a generated vendoring step, and rewrite `_src_path` in every existing
service's `.copier-answers.yml` — a `_migrations` step, since Copier has no
built-in way to re-home a subproject. Cost scales with the number of minted
services, so the decision point is before the first one ships.
