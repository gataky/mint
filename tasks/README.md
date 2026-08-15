# Implementation chunks

`../prompt.md` is the specification — the durable statement of what Mint must
be. It is deliberately too large to hand to an agent in one piece; doing so
produces partial compliance with no signal about which parts got dropped.

These files break it into ordered chunks. **One chunk per agent session.**
Each names the spec sections it implements, what must already exist, what is
explicitly out of scope, and what "done" means in checkable terms.

## Order

| # | chunk | size | depends on |
| --- | --- | --- | --- |
| 00 | [Bootstrap the mint repo](00-bootstrap.md) | S | — |
| 01 | [Decisions and ADRs](01-decisions.md) — research, no code | M | 00 |
| 02 | [Copier scaffolding + harness skeleton](02-copier-scaffolding.md) | L | 01 |
| 03 | [Configuration](03-config.md) | M | 02 |
| 04 | [Logging](04-logging.md) | M | 03 |
| 05 | [Error contract](05-error-contract.md) | S | 03 |
| 06 | [HTTP server, middleware, lifecycle, health](06-http-server.md) | L | 04, 05 |
| 07 | [Operation registry + widgets example](07-registry-and-widgets.md) | L | 06 |
| 08 | [Tracing and metrics](08-observability.md) | M | 07 |
| 09 | [Generated discovery docs](09-discovery.md) | M | 08 |
| 10 | [Docs, proof, and tag](10-wrap-up.md) | M | 09 |

**Human checkpoints** — stop and review before continuing past these:

- **After 02.** The skeleton is what everything else is built on. If the
  copier layout, delimiters, or question set are wrong, fixing it later means
  touching every template file.
- **After 07.** The registry is upstream of routing, OpenAPI, and `llms.txt`.
  If its shape is wrong, three chunks get rewritten.

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
   durable record.

4. **Flag, don't guess.** The spec's "Things to flag back to me" list is
   binding. If a chunk runs into one of those, or into a genuine Go/Python
   idiom mismatch, stop and report the tradeoff rather than picking
   silently.

5. **Pin every version.** No floating dependencies, no "latest at generation
   time" resolution. See spec § Version pinning.

6. **Leave the repo green.** At the end of every chunk, `make parity`,
   `make verify`, and `make test` all pass. If a chunk can't leave it green,
   say so explicitly and say why.

7. **Don't build ahead.** Each chunk has an "Out of scope" section. Respect
   it — building ahead is how the checkpoints stop being useful.

## Deferred, on purpose

Do not build these in any chunk: Dockerfiles, docker-compose, CI pipelines,
Kubernetes manifests, MCP servers, authentication. See the deferral table in
the spec — each has a named seam so it stays cheap to add later, and chunk 01
writes the ADRs that record why.
