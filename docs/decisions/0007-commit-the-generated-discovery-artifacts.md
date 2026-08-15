# 0007 — Commit the generated discovery artifacts

**Status:** accepted (2026-08-14)
**Date:** 2026-08-14
**Chunk:** [01 — Decisions and ADRs](../../tasks/01-decisions.md)

## Context

`openapi.json` and `llms.txt` are generated from the operation registry by
`make agents-docs`. The service serves both at runtime regardless of this
decision — `GET /openapi.json` and `GET /llms.txt` are built from the
registry in the running process, not read from disk. So the question is
narrow: does the *file* live in git, or in `.gitignore`?

The spec's own framing is that committing makes drift show up as a PR diff,
while gitignoring treats them as pure build output. The case against
committing that needed testing rather than reasoning is the merge-conflict
one: a committed generated file is claimed to be a conflict surface,
particularly for `copier update`, which is the workflow the whole project
exists to support.

### The spike

A minimal Copier template (copier 9.17.1) with a `gen.py` standing in for
`make agents-docs`, a generated service, a template version bump that changes
the generator's output shape, and both variants of the question.

**1. `copier update` does not conflict on the committed artifact — at all.**

```
$ copier update --defaults --vcs-ref v1.1.0
$ git status --porcelain
 M .copier-answers.yml
 M gen.py
$ grep -rl '<<<<<<<' . --exclude-dir=.git
(none)
```

The reason is structural and it undercuts the main objection: Copier
three-way-merges only the files it *renders*. `openapi.json` is not one of
them — its content depends on the generated service's own registry, so the
template cannot possibly ship a version of it. Copier has no "old render" and
no "new render" for it, and therefore never touches it. **This holds only so
long as the template never ships `openapi.json` or `llms.txt` as template
files**, not even as placeholders. That is the precondition, and it is
recorded as a rule below.

**2. After the update, the committed artifact is stale, and the drift check
catches it.**

```
STALE -> make agents-docs exits non-zero. diff:
   ],
+  "info": {
+    "title": "svc"
+  }
```

That is the intended behaviour: a template bump that changes the generated
API surface produces a visible, reviewable diff in the same pull request as
the template bump. In the gitignored variant, the same `copier update` yields
a PR diff of `gen.py | 2 +-` and nothing at all about the resulting change to
the service's public API description.

**3. `copier update` refuses to run on a dirty destination.**

```
Destination repository is dirty; cannot continue. Please commit or stash your
local changes and retry.
```

This is the one genuine ergonomic edge for gitignoring: an ignored artifact
never dirties the tree, so `copier update` runs without a preceding commit.
With a committed artifact, a stale regenerated file must be committed or
stashed first. This is one extra `git commit` in a workflow that already
requires a clean tree for other reasons.

**4. The real conflict surface is branch merges, not `copier update`.** Two
feature branches that each add an operation and regenerate:

```
Auto-merging gen.py
CONFLICT (content): Merge conflict in gen.py
Auto-merging openapi.json
CONFLICT (content): Merge conflict in openapi.json
```

The source conflicts *and* the derivative conflicts — one logical conflict
reported twice. Worse, git's default text merge leaves conflict markers inside
the JSON, which makes the file unparseable mid-merge:

```
openapi.json parses as JSON mid-conflict? json.decoder.JSONDecodeError
```

That is fixable. With `openapi.json -merge` in `.gitattributes`, git still
reports the conflict but leaves a valid file in the worktree:

```
CONFLICT (content): Merge conflict in openapi.json
openapi.json parses as JSON mid-conflict? YES
```

And the resolution is mechanical rather than a judgement call — resolve the
registry conflict, re-run the generator, and the drift check confirms the
result:

```
resolved ops: ['widgets.list', 'widgets.get', 'widgets.delete',
               'widgets.update', 'widgets.archive', 'widgets.purge']
FRESH: 'resolve source, re-run make agents-docs' is a complete resolution
```

## Decision

**Commit `openapi.json` and `llms.txt` at the root of every generated
service.** With four supporting rules, all of which are part of chunks 02 and
09:

1. **Neither file is ever a template file.** `templates/*/template/` must not
   contain `openapi.json`, `llms.txt`, or `.jinja` versions of them, not even
   empty placeholders. They come into existence only from `make agents-docs`,
   which `_tasks` runs at generation time. This is what keeps `copier update`
   free of conflicts on them, and it should be asserted by the parity check
   rather than remembered.
2. **`make agents-docs` regenerates and exits non-zero when the committed
   output differs.** This is the drift check the spec already requires; this
   ADR only fixes what it compares against. It runs in `make lint`'s
   neighbourhood locally and will run in CI in Phase 2.
3. **`.gitattributes` in every generated service carries `openapi.json
   -merge` and `llms.txt -merge`,** so a branch-merge conflict leaves a valid
   file rather than a JSON document with conflict markers in it. The generated
   `.gitattributes` and the README document the resolution in one line:
   *resolve the conflict in the registry, then run `make agents-docs`.*
4. **The runtime endpoints remain registry-derived,** never file-derived. The
   service must not read `openapi.json` from disk to serve `/openapi.json`. If
   it did, the committed file would become load-bearing at runtime and a stale
   commit would become a production bug rather than a failed check.

## Alternatives considered

**Gitignore both as pure build output.** The principled position, and the one
that is right for most generated files — build output in git is usually a
smell. It loses here on one specific ground: these two files are not build
output, they are the *published interface description*. The strongest concrete
form of the argument is what a reviewer sees. With the artifacts gitignored, a
pull request that renames a field, changes a status code, drops an operation,
or alters a schema shows up as a diff in a handler or a registry entry, and
the reviewer must reconstruct the API-surface consequence from the source.
With them committed, the consequence is the diff. For a project whose first
principle is "one set of facts, several representations," making the
representation that consumers depend on invisible to review is the wrong
trade.

The secondary reason is consumers. A committed `openapi.json` can be fetched
at a stable URL by a client generator, a contract-diff job, a documentation
site, or an agent, without booting the service, without a container runtime,
and without network access to a deployed environment. Phase 2's CI can run a
breaking-change check on the spec as a plain file diff. All of that requires
either a committed file or an artifact-publishing pipeline that does not exist
and would have to be built and maintained.

The honest cost of losing this alternative is stated in Consequences below;
it is not zero.

**Commit `openapi.json` but gitignore `llms.txt`.** Considered because the two
files have different audiences: the OpenAPI spec has external consumers, while
`llms.txt` is a short index primarily useful to an agent that has already
reached the running service. Rejected for consistency more than substance —
two generated files with two different rules means `make agents-docs` has two
behaviours, the drift check has two modes, and `docs/agents.md` has to explain
why. The marginal cost of committing a short text file is close to zero, and
the same review argument applies weakly but genuinely: if `llms.txt` stops
pointing at a doc that was deleted, a PR diff is where that should surface.

**Commit them, but generate into a `gen/` or `dist/` subdirectory.** Cosmetic
improvement — it groups generated files and makes a `.gitattributes` glob
tidier. Rejected because the spec's generated-service layout puts them at the
root, `/llms.txt` and `/openapi.json` are conventionally root-served paths,
and the README already links them from the root. Not worth a layout deviation.

**Commit a normalized/canonical form to shrink diffs** (sorted keys, no
pretty-printing). Partially adopted: the generator must emit deterministic
output — sorted keys, stable operation order, trailing newline — or the drift
check will fail spuriously on map-iteration order, which in Go it certainly
would. MCP's own 2026-07-28 revision now asks servers for deterministic
`tools/list` ordering for the same reason. Not adopted: minifying to shrink
diffs, which would trade the review benefit that motivates the whole decision
for a smaller line count.

## Consequences

**What this makes easy.** A reviewer sees API-surface changes as API-surface
changes. A template bump that changes the generated spec produces a visible
diff in the upgrading service's PR rather than a silent behaviour change.
Consumers get the spec from git. Phase 2 gets a spec-diff CI job for free.
`make agents-docs` has exactly one job and one failure mode.

**What this makes hard, and it is a real cost.** Every PR that touches the
registry carries a second, larger, machine-generated diff, and reviewers
learn to skip it — which is the standard failure mode of committed generated
files and the single strongest argument against this decision. Some of that is
mitigated by the file being genuinely interesting (unlike a lockfile), and
some by keeping the output deterministic and human-readable so the diff is
small and legible when the change is small. None of it is fully mitigated.

Branch merges conflict twice for one logical change. `.gitattributes -merge`
keeps the file valid and the documented resolution is mechanical, but it is
still an extra step that will confuse someone the first time.

`copier update` needs a clean tree, so a service whose committed artifact has
drifted must commit or stash before updating. Minor, and arguably a feature:
you should not be updating a template on top of uncommitted drift.

**What would reverse this.** If `openapi.json` grows past the point where its
diff is reviewable — a service with a hundred operations and deeply nested
schemas — the review argument that motivates this ADR stops applying, because
nobody reads a four-thousand-line diff either way. At that point the right
move is not to gitignore it but to replace the raw diff with a semantic
spec-diff check in CI, keep the file committed for consumers, and mark it
`linguist-generated=true` so review tooling collapses it by default. Revisit
this when the first real service crosses that line, not before.
