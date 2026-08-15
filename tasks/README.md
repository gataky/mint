# Implementation chunks

`../prompt.md` is the specification — the durable statement of what Mint must
be. It is deliberately too large to hand to an agent in one piece; doing so
produces partial compliance with no signal about which parts got dropped.

These files break it into ordered chunks. **One chunk per agent session.**
Each names the spec sections it implements, what must already exist, what is
explicitly out of scope, and what "done" means in checkable terms.

**The ADRs in `../docs/decisions/` outrank the spec.** Chunk 01 ran real code
spikes and several of them contradicted assumptions the spec was built on —
per-template `copier.yml` files don't work, per-template tags are silently
discarded, pure reflection produces an OpenAPI document that validates and
lies, neither language's turnkey HTTP metrics instrumentation is usable. All
eleven ADRs are approved. Where a chunk file and the spec disagree, follow the
chunk file and the ADR it cites.

## Order

| # | chunk | size | depends on | status |
| --- | --- | --- | --- | --- |
| 00 | [Bootstrap the mint repo](00-bootstrap.md) | S | — | ✅ done |
| 01 | [Decisions and ADRs](01-decisions.md) — research, no code | M | 00 | ✅ done — 11 ADRs, all approved |
| 02 | [Copier scaffolding + harness skeleton](02-copier-scaffolding.md) | L | 01 | ✅ done — acceptance green, checkpoint cleared |
| 03 | [Configuration](03-config.md) | M | 02 | ✅ done |
| 04 | [Logging](04-logging.md) | M | 03 | next |
| 05 | [Error contract](05-error-contract.md) | S | 03 | |
| 06 | [HTTP server, middleware, lifecycle, health](06-http-server.md) | L | 04, 05 | |
| 07 | [Operation registry + widgets example](07-registry-and-widgets.md) | L | 06 | |
| 08 | [Tracing and metrics](08-observability.md) | M | 07 | |
| 09 | [Generated discovery docs](09-discovery.md) | M | 08 | |
| 10 | [Docs, proof, and tag](10-wrap-up.md) | M | 09 | |

Chunk 01 is complete: eleven ADRs (`docs/decisions/0001`–`0011`), all approved
by the human. Read the ones each chunk cites before starting it — they carry
the reasoning and the measured evidence, and several of them exist precisely
because the obvious implementation was tried and failed. Chunks 02 onward are
sequential and each builds on the last; run those one at a time.

**Human checkpoints** — stop and review before continuing past these:

- **After 02.** The skeleton is what everything else is built on. If the
  copier layout, delimiters, or question set are wrong, fixing it later means
  touching every template file. ADR 0009 already settled the layout — one
  root `copier.yml`, a Jinja-rendered `_subdirectory`, one shared question
  set — so this checkpoint is about whether it was *built* right, not about
  re-opening the design.
- **After 07.** The registry is upstream of routing, OpenAPI, and `llms.txt`.
  If its shape is wrong, three chunks get rewritten. ADR 0001 fixes that
  shape, including the `Errors` field, the placement tags, and the
  `EnumValues()` method that pure reflection provably cannot replace.

## Standing rules — these apply to every chunk

Every chunk inherits these. They are stated here once rather than repeated
eleven times, which is the same principle the spec applies to everything
else.

1. **Both languages, same chunk.** Never complete Go and then port to
   Python. Build the Go and Python sides of a chunk together and finish with
   them at parity. Building one language to completion first is exactly the
   drift the whole project exists to prevent.

2. **The harness grows with the feature.** Every chunk that adds a
   guarantee also adds the check that enforces it — to `scripts/parity.sh`,
   `scripts/verify-template.sh`, or the generated services' tests. A chunk
   that adds a rule without adding its check is not done. Do not defer
   checks to chunk 10.

3. **Non-obvious decisions become ADRs.** If you make a call the spec
   doesn't dictate, write `docs/decisions/NNNN-<slug>.md` (context /
   decision / consequences) as part of the chunk. Chat scrollback is not a
   durable record. **0001–0011 are approved and binding.** If implementation
   contradicts one, supersede it with a new ADR — never edit it in place,
   and never quietly build something else.

4. **Flag, don't guess.** The spec's "Things to flag back to me" list is
   binding. If a chunk runs into one of those, or into a genuine Go/Python
   idiom mismatch, stop and report the tradeoff rather than picking
   silently. Items an ADR has already settled are stated as decisions in the
   chunk files, not as questions — don't re-open them.

5. **Pin every version.** No floating dependencies, no "latest at generation
   time" resolution. No ranges, no `latest`, no `^`/`~`, anywhere. `uv.lock`
   and `go.sum` are committed.

   **The pin list is the manifests themselves** — `.tool-versions`, `go.mod`
   (including `tool` directives), `pyproject.toml`, `uv.lock` — not a table
   in a document ([ADR 0015](../docs/decisions/0015-the-manifests-are-the-pin-list.md)).
   ADR 0011's table is a snapshot of what chunk 01 decided, not a live index;
   it went stale twice during chunk 02 alone. A chunk that adds a dependency
   states the pin in its handoff. Write an ADR for the *choice* — "tint
   rather than zap" — never merely to register a version number.

6. **Leave the repo green.** At the end of every chunk, `make parity`,
   `make verify`, and `make test` all pass. If a chunk can't leave it green,
   say so explicitly and say why.

7. **Don't build ahead.** Each chunk has an "Out of scope" section. Respect
   it — building ahead is how the checkpoints stop being useful.

8. **One template root, one question set** (ADR 0009). There is a single
   `copier.yml` at the git repo root with
   `_subdirectory: "templates/[[ language ]]-service/template"`. There are no
   per-template `copier.yml` files — Copier only treats a path as VCS-tracked
   when it is the repo root, so a template in a subdirectory gets no
   `_commit`, no mint mark, and `copier update` exits 1 forever. Corollaries
   every chunk inherits: `language` is a recorded answer and **no generated
   file may branch on it** beyond selecting the subdirectory; anything shared
   lives in `templates/_common/` and reaches each template by relative
   symlink.

9. **Versions are plain repo-wide semver** (ADR 0009). Tags are `v1.2.0`.
   Per-template tags (`go-service/v1.2.0`) are discarded by Copier as
   non-PEP-440 and silently fall back to HEAD, which leaks untagged work into
   generated services. One tag, one root `CHANGELOG.md` with entries scoped
   `go-service:` / `python-service:` / `common:`. Semver level is judged by
   the effect on a *generated service*, not by which directory changed.

## Deferred, on purpose

Do not build these in any chunk: Dockerfiles, docker-compose, CI pipelines,
Kubernetes manifests, MCP servers, authentication. See the deferral table in
the spec — each has a named seam so it stays cheap to add later, and chunk 01
wrote the ADRs that record why: **0004** (MCP; the seam is
`internal/transport/http/` nesting one level deeper and a transport-agnostic
registry) and **0005** (auth; the seam is a named, empty slot in the frozen
middleware chain).

Two seams are thinner than they look and both ADRs say so plainly: the
middleware chain does not cross the MCP seam (0004), and a gateway does not
cover a stdio transport (0005). Don't build against them as if they were free.
