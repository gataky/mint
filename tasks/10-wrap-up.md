# 10 — Docs, proof, and tag

**Spec:** § Parity enforcement, § Copier mechanics (versioning, updates),
§ asdf + direnv, § Deliverables
**Depends on:** 09. **ADR 0009 is binding here** — the tag scheme in spec
§ Versioning does not work and this chunk cuts a different tag than the spec
says. ADR 0011 governs the pin table the README documents.
**Size:** M
**Standing rules:** [tasks/README.md](README.md#standing-rules--these-apply-to-every-chunk)

## Goal

Close out Phase 1: finish the documentation, prove the harnesses actually
catch drift rather than merely passing, prove `copier update` works, and tag
the first release so the mint mark renders.

## Do

1. **Complete `scripts/parity.sh`** — the eight checks from spec § Parity
   enforcement **as amended by the ADRs**, plus the checks earlier chunks
   added on top. Each check should name what diverged and where, not just
   exit 1. The amendments to carry forward:

   - **#1 is an assertion, not a diff** (ADR 0009). There is one question
     set, so there is nothing to diff: assert that every question except
     `module_path` and `package_name` is unconditional and that those two are
     `when:`-gated on `language` and nothing else.
   - **Log parity is tier 2 only, byte-identical; tier 1 is compared on key
     names** (ADR 0010).
   - **Metrics parity compares parsed `(family, sorted label keys, type)`
     over a Mint-owned allowlist, never raw text** (ADR 0003).
   - Config parity includes the ordered-source-list assertion — both
     languages report exactly `["yaml", "env"]` (ADR 0006).
   - The templates contain no `openapi.json` or `llms.txt` (ADR 0007).

2. **Complete `scripts/verify-template.sh`** — generate both from the repo
   root with `-d language=go` / `-d language=python`, build, boot, exercise
   `/healthz`, `/readyz`, `/metrics`, all three widgets endpoints,
   `/llms.txt`, `/openapi.json`; assert a log line in each tier and an
   exported span; SIGTERM **against the split port configuration** and assert
   clean drain; tear down. Assertions, not eyeballing.

3. **Prove drift detection.** For **every** parity check — not just the
   spec's original eight — introduce the drift it's meant to catch, confirm
   it fails, and revert. A parity suite that has never failed is not known to
   work. Record the results as a table in the handoff: one row per check,
   what was broken, what the failure output said.

   Four of these are worth doing deliberately because the ADRs identified
   them as silent-failure modes: deleting Python's `capture_signals` line
   (chunk 06), deleting Python's `settings_customise_sources` override (chunk
   03), removing the explicit nested-key sort from the Python logger (chunk
   04), and adding a `route`-labelled metric outside `internal/observability`
   (chunk 08).

4. **Prove `copier update`.** Generate a service from the current template,
   commit it, make a non-trivial template change (add a config key and a
   Makefile target), tag it, run `copier update` in the generated service,
   and confirm the change lands cleanly. Do this for both languages.
   Document the workflow in the README from what you actually observed, not
   from the Copier docs.

   Three behaviours ADR 0009 measured and that the README should state
   because a user will hit them:

   - **Untagged work on `main` is correctly held back.** A service pinned to
     `v0.1.0`, with an untagged WIP commit on the template, updates to the
     last *tag*. Prove it — that property is the entire reason the tag scheme
     changed.
   - **A repo-wide release reaches the other language's services as two
     Copier-owned lines** (`_commit` and the mint mark), with no code churn
     and no conflict risk. Show the `git diff --stat`.
   - **`copier check-update` produces false positives**: a Go service is told
     `{"update_available": true}` for a Python-only release. `CHANGELOG.md`
     is the only thing that answers "is there anything in it for me". If this
     becomes a nuisance the fix is a scope-aware wrapper in `scripts/`, not a
     change to the tag scheme.

   Also: `copier update` **refuses to run on a dirty destination**, so a
   service whose committed `openapi.json` has drifted must commit or stash
   first (ADR 0007). Document that as part of the workflow.

   Do **not** put `Make sure Git >= 2.24 is installed to improve updates.` in
   the README's troubleshooting section. Copier prints it under git 2.55.0;
   it is a cosmetic fallback path, not a real version problem, and enshrining
   it as advice sends people chasing a non-issue.

5. **Top-level `README.md`**: what Mint is; one-time machine setup (asdf,
   direnv, copier — the only place this is documented, and the pins are ADR
   0011's: `golang 1.26.6`, `python 3.14.7`, `uv 0.12.5`); how to generate a
   service — `copier copy . <dest> -d language=go|python`, **from the mint
   repo root, because there is one `copier.yml` and it lives there**; how to
   run `copier update`; how to change a template, including that a copier
   question is now added **once**, to the shared document, and that
   `templates/_common/` reaches both languages by symlink; the versioning and
   tagging policy; what Phase 2 and 3 will add.

   The versioning section states ADR 0009's rules directly:

   - Tags are plain repo-wide semver, `v<MAJOR>.<MINOR>.<PATCH>`. A tag
     `packaging.version.Version()` can't parse is a release-process bug —
     Copier silently discards it and falls back to HEAD, which leaks
     unreleased template commits into services.
   - **Semver level is judged by the effect on a generated service**, not by
     which directory changed. MAJOR: anything a service can't absorb by merge
     — removing or renaming a question, renaming a generated directory,
     renaming a config key or env var, changing the error-body contract or
     the reserved log field set; every MAJOR needs a `_migrations` entry.
     MINOR: additive — a new question with a default, a new file, a new
     Makefile target, a new middleware in a reserved slot. PATCH: fixes and
     pinned-toolchain bumps that change no interface.
   - A `templates/_common/` change bumps the single version at whatever level
     its effect on a generated service warrants. It reaches both languages by
     construction; there is no version in which it reaches only one.

6. **Top-level `AGENTS.md`**: for an agent maintaining *this* repo — the two
   governing principles, the `_common/` vs per-language split (and the
   symlink mechanism), the single root `copier.yml` and why there is only
   one, the parity rules and how to run them, how to add a copier question,
   where the spec and ADRs live, the eleven ADRs one line each, and the
   deferral table with pointers to the ADRs that explain each.

7. **Generated `README.md`** — finish it: what the service is, quickstart,
   the Makefile targets, the mint mark, links to AGENTS.md, `/llms.txt`,
   `/openapi.json`, and the shared `docs/` files; the note that swapping the
   OTel exporter for a Collector is a config change; a `docker run` line for
   local Jaeger; and a justification for every dependency, per spec.

   Five things the ADRs require this README to say, because a user will
   otherwise be surprised:

   - **Both ports**, prominently. `/healthz` is not on the port you just
     curled, and every developer learns this the same way (ADR 0008).
   - **The application never reads `.env`** — that's direnv's job, and
     values from it beat `config/config.local.yaml` (ADR 0006).
   - **Go client generation needs the committed 3.0.3 document**, because
     `oapi-codegen` cannot read OpenAPI 3.1 (ADR 0001).
   - **The mint mark's version is repo-wide**, so it can advance on a release
     that contained nothing for this language; `CHANGELOG.md` is where that
     question is answered (ADR 0009).
   - The dependency justifications must cover the ones the ADRs added:
     `structlog` (zero transitive deps, pure Python), `lmittmann/tint` (Go
     tier 1 colour — `slog.NewTextHandler` emits no ANSI at all),
     `go-playground/validator`, and the ~212 `// indirect` requires that
     `go get -tool golangci-lint` pulls into `go.mod` (ADR 0011 accepts this
     deliberately; the escape hatch is a separate `tools/go.mod`).

8. **Verify the direnv/asdf path end to end** on a clean shell: generate,
   `direnv allow`, `make run`, with no other manual setup. Both languages.

9. **One `CHANGELOG.md` at the mint repo root**, with entries scoped
   `go-service:` / `python-service:` / `common:` so a reader can tell at a
   glance whether a release contains anything for their language. **This
   replaces spec § Versioning's "keep `CHANGELOG.md` per template"** (ADR
   0009 decision 6) — there are no per-template changelogs.

   **Tag `v0.1.0`.** One tag, repo-wide. Not `go-service/v0.1.0`, not
   `python-service/v0.1.0` — Copier discards those as non-PEP-440, reports
   "No git tags found in template; using HEAD as ref", and generation then
   *looks* like it worked while nothing is actually pinned.

10. **Confirm the mint mark renders** in a service generated from the tagged
    template — reading the version from `_commit` and the template name from
    the `language` answer — and still degrades gracefully (line omitted
    entirely) from an untagged checkout.

11. **Note the standing maintenance obligation** in the README or AGENTS.md:
    seven tools plus eleven Python packages are pinned exactly, and they go
    stale within weeks. Without an automated bump PR in Phase 2, "latest
    stable at authoring time" quietly becomes "latest stable in August 2026"
    (ADR 0011).

## Out of scope

Anything from the deferral table. Do not start Phase 2.

## Deliverables

- Complete `make parity` (the spec's eight as amended, plus the checks
  chunks 03–09 added) and `make verify`
- A drift-detection results table, one row per check
- A `copier update` walkthrough, verified in both languages, including the
  untagged-work-held-back proof
- Top-level README and AGENTS.md; generated README finished
- One root `CHANGELOG.md`, scoped entries
- Tag `v0.1.0`

## Acceptance criteria

- `make parity`, `make verify`, `make test`, and `make lint` all pass at the
  mint root.
- **Every** parity check has been individually proven to fail on the drift it
  targets — including the four silent-failure modes named in item 3.
- `copier update` lands a template change into an existing generated service
  in both languages, and an untagged commit on the template's `main` does
  **not** reach the service.
- A Python-only release produces a two-line, conflict-free diff in a Go
  service.
- A clean-shell run of generate → `direnv allow` → `make run` works with no
  other setup, both languages.
- A generated service's README shows the mint mark with `v0.1.0` and the
  template name derived from the `language` answer.
- Generating from an untagged checkout omits the mint mark line entirely
  rather than rendering a broken one.
- `make help` output from the two generated services is identical except for
  the service name.
- `git tag -l` at the mint root shows `v0.1.0` and no slash-namespaced tags.
- Every ADR from chunk 01 is still accurate, or has been superseded by a new
  ADR rather than edited in place. Note that ADR 0011's pin table is expected
  to have gained a `lmittmann/tint` row from chunk 04 — check it did.

## Flag back before finishing

- Any parity check that couldn't be made to fail on its target drift —
  that's a check that doesn't work, and it's worse than no check because it
  reads as a guarantee.
- Anything from spec § "Things to flag back to me" that got decided during
  implementation without an ADR.
- Whether `copier check-update`'s false positives are annoying enough in
  practice to justify the scope-aware wrapper ADR 0009 names as the fix.
- Your assessment of what Phase 1 got wrong or left awkward, while it's
  fresh. Phase 2 starts from this, and the honest version is more useful
  than a clean one. ADR 0009 already names one candidate for that list: the
  repo-wide version number stops meaning "something changed for me", and
  `CHANGELOG.md` is the only mitigation.

*Settled, do not re-open:* plain repo-wide semver tags and the single root
`CHANGELOG.md`. ADR 0009, approved — the spec's per-template tagging was
spiked and fails silently, which is worse than failing loudly.
