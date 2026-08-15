# 09 — Generated discovery docs

**Spec:** § AI-agent discoverability, § Makefile parity (`agents-docs`)
**Depends on:** 07 (the registry), 08; ADR 0001 and ADR 0007
**Size:** M
**Standing rules:** [tasks/README.md](README.md#standing-rules--these-apply-to-every-chunk)

## Goal

Turn the registry into the three representations that make a running service
self-describing — `/openapi.json`, `/llms.txt`, and AGENTS.md's command block
— with a drift check that fails when any of them falls out of date.

This is where "one set of facts, several representations" either holds or
doesn't.

## Do

1. **`GET /openapi.json`**, generated from the registry, per ADR 0001.
   FastAPI gives Python most of this for free — but it must be driven by the
   registry, not by FastAPI's own route decorators, or Python has a second
   authoring location and the whole design leaks. Go reflects over the
   registry.

   The spec must be OpenAPI 3.1, include the `problem+json` error responses
   from chunk 05, and validate against a schema validator.

2. **`GET /llms.txt`**, generated — never hand-written. A short index
   pointing at the OpenAPI spec, the `docs/` files, and the widgets example.
   Same generator shape in both languages.

3. **AGENTS.md's generated command block.** Delimited by markers, written by
   `make agents-docs` from the Makefile's own `##` comments. Commands are
   neither restated by hand (drift) nor merely linked (useless to an agent
   that then has to go read a Makefile).

4. **`make agents-docs`** regenerates all three and **exits non-zero if the
   committed output is stale.** This is the drift check for everything in
   this chunk. Handle the committed-vs-gitignored question per ADR 0007.

5. **`docs/agents.md`** — the source of truth for what an AGENTS.md must
   contain. Both language templates render their AGENTS.md from it: the
   three-layer architecture and its rules, the registry and how to add an
   operation, where widgets lives, the error taxonomy, and the explicit
   "don't do this" boundaries (service layer never imports `net/http` or
   FastAPI request types; nothing outside `internal/config` reads an env
   var; never label a metric with an unbounded value).

6. **Complete the registry-coverage test** from chunk 07: every registered
   operation is routable *and* appears in `/openapi.json` *and* in
   `/llms.txt`. This is the test that makes the design claim true.

7. **`CLAUDE.md` symlink** in generated services, verified present and
   pointing at AGENTS.md.

## Out of scope

MCP (deferred — see ADR 0004). Swagger UI or any HTML docs viewer. Client
SDK generation, though ADR 0001 should have established the spec is good
enough to support it.

## Deliverables

- `/openapi.json` and `/llms.txt` served by both generated services
- `make agents-docs` with its staleness check, in both
- `docs/agents.md`, and AGENTS.md rendered from it in both templates
- Completed registry-coverage test

## Acceptance criteria

- `/openapi.json` validates against an OpenAPI 3.1 schema validator in both
  languages.
- The operation lists in the Go and Python specs are identical — same
  operation IDs, paths, methods, and response codes.
- Every registry operation appears in `/openapi.json` and `/llms.txt`;
  nothing appears in either that isn't in the registry.
- Adding an operation to the registry makes it appear in routes, OpenAPI,
  and `llms.txt` with **no other edit**. Demonstrate this — add one, show
  all three update, then revert.
- `make agents-docs` exits non-zero when generated output is stale.
  Demonstrate by editing a `##` comment without regenerating.
- Both generated AGENTS.md files have the same section structure and state
  the same boundaries.
- `scripts/parity.sh` gains check #6 (operation lists from both
  `/openapi.json` files) and an AGENTS.md structure diff.
- `scripts/verify-template.sh` fetches and validates both endpoints.

## Flag back before finishing

- **Whether FastAPI could genuinely be driven from the registry** rather
  than from its own decorators. This is the most likely failure point in the
  chunk. If it can't be cleanly, Python has two authoring locations and you
  should say so rather than accept the drift quietly.
- Whether Go's reflected spec is materially poorer than Python's — if one
  language produces a spec good enough for client generation and the other
  doesn't, that's a parity break worth naming even though both "work."
- ADR 0007's committed-vs-gitignored call, if building the drift check
  changed your view of it.
