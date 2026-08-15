# 09 — Generated discovery docs

**Spec:** § AI-agent discoverability, § Makefile parity (`agents-docs`)
**Depends on:** 07 (the registry), 08. **ADRs 0001 and 0007 are binding
here** — 0001 adds a build-time `go/ast` pass and a second, downgraded
document that the spec doesn't mention; 0007 settles committed-vs-ignored and
attaches four rules to it.
**Size:** M
**Standing rules:** [tasks/README.md](README.md#standing-rules--these-apply-to-every-chunk)

## Goal

Turn the registry into the three representations that make a running service
self-describing — `/openapi.json`, `/llms.txt`, and AGENTS.md's command block
— with a drift check that fails when any of them falls out of date.

This is where "one set of facts, several representations" either holds or
doesn't.

## Do

1. **`GET /openapi.json`**, generated from the registry, per ADR 0001. Go
   reflects over the registry (~520 lines for the reflector in the spike).
   Python is driven from the registry through the glue chunk 07 built — **not
   from FastAPI's own route decorators**, or Python has a second authoring
   location and the whole design leaks.

   **OpenAPI 3.1 is canonical and is what `/openapi.json` serves.** Include
   the `problem+json` error responses from chunk 05, driven by each
   operation's `Errors` field so `widgets.get` advertises its 404 and
   `widgets.list` does not.

   Three structural rules the spike proved necessary:

   - **Publish named types as their own components, never inline.** Emitting
     an enum inline made `oapi-codegen` mint four distinct Go types for one
     domain enum (`WidgetStatus`, `CreateWidgetInputStatus`,
     `UpdateWidgetInputStatus`, `WidgetsSearchParamsStatus`). After the fix:
     one `Status` type, three constants.
   - **Attach descriptions to `$ref`s via `allOf`**, so the same document
     downgrades to 3.0 cleanly.
   - **Inject `Problem` into `components` explicitly** in Python — FastAPI
     only emits schemas for models it sees in a signature — and **strip
     `422`** from the generated document, since chunk 07 remapped
     `RequestValidationError` to 400 problem+json.

2. **The `go/ast` doc-comment pass.** Go has **no runtime access to doc
   comments at all**, so reflection alone produces a structurally correct
   document with no field descriptions. Build `cmd/docgen` (~75 lines): it
   walks the package's AST, harvests field doc comments into
   `fielddocs.json`, and the generator loads that file. `make agents-docs`
   runs it *before* generating.

   Measured effect in the spike: 33 missing-description diagnostics down to
   1. The remaining one is `map[string]any`, which is genuinely unschemable —
   **report it as a diagnostic rather than papering over it.**

   This degrades rather than breaks: if `make agents-docs` isn't run, the
   served spec has structure but no descriptions. Say so in the generated
   README.

3. **Emit a mechanically downgraded OpenAPI 3.0.3 copy alongside the 3.1
   document.** This is not optional and it is not our defect:

   ```
   $ oapi-codegen -config cfg31.yaml openapi.json
   error loading swagger spec: json: cannot unmarshal number into field
     Schema.exclusiveMinimum of type bool
   ```

   **`oapi-codegen` v2.5.0 cannot read OpenAPI 3.1 at all** — 3.1 made
   `exclusiveMinimum` a number and `kin-openapi` still models it as the 3.0
   boolean. FastAPI's own 3.1 output fails identically, so this is an
   ecosystem problem that affects any generated service. Against a downgraded
   3.0.3 copy, `oapi-codegen` produced 32 KB of Go client code that compiles.
   `openapi-typescript` 7.13.0 consumes the **native 3.1** document without
   complaint.

   The downgrade is ~20 lines: rewrite `exclusiveMinimum`/`exclusiveMaximum`
   from numbers to the 3.0 boolean-plus-`minimum`/`maximum` form, and drop
   `jsonSchemaDialect`. Serve 3.1 at `/openapi.json`. Commit the 3.0 copy
   under the same rules as the 3.1 one (item 5) and give it a name that says
   what it is. The generated README must state plainly that Go client
   generation needs the 3.0 file, because consumers will hit this.

4. **`GET /llms.txt`**, generated — never hand-written. A short index
   pointing at the OpenAPI spec, the `docs/` files, and the widgets example.
   Same generator shape in both languages.

5. **Commit `openapi.json` and `llms.txt`** at the root of every generated
   service, per ADR 0007, with its four supporting rules:

   - **Neither file is ever a template file.** `templates/*/template/` must
     not contain them, not even as empty placeholders, not even as `.jinja`.
     Copier three-way-merges only files it *renders*; because it has no old
     render and no new render for these, `copier update` never touches them
     and never conflicts on them. That property holds **only** while the
     precondition does. Chunk 02 added the parity assertion; keep it passing.
   - **`make agents-docs` regenerates and exits non-zero when the committed
     output differs.** That is the drift check.
   - **`.gitattributes` carries `openapi.json -merge` and `llms.txt -merge`**
     (chunk 02 shipped it). Without it, a branch-merge leaves conflict
     markers inside the JSON and the file doesn't parse mid-merge; with it,
     git still reports the conflict but leaves a valid file. The documented
     resolution is one line: *resolve the conflict in the registry, then run
     `make agents-docs`.*
   - **The runtime endpoints stay registry-derived, never file-derived.** The
     service must not read `openapi.json` from disk to serve
     `/openapi.json`. If it did, a stale commit would become a production bug
     rather than a failed check.

   **Output must be deterministic** — sorted keys, stable operation order,
   trailing newline — or the drift check fails spuriously on Go's map
   iteration order. Do not minify: the whole review argument for committing
   depends on the diff being legible.

   `_tasks` runs `make agents-docs` at generation time, so a freshly minted
   service has both files and a clean tree.

6. **AGENTS.md's generated command block.** Delimited by markers, written by
   `make agents-docs` from the Makefile's own `##` comments. Commands are
   neither restated by hand (drift) nor merely linked (useless to an agent
   that then has to go read a Makefile).

7. **`make agents-docs` runs three checks, each exiting non-zero:**

   - the structural checks from chunk 07 (placement tags, path agreement, no
     body on GET/DELETE/HEAD, unique operation names);
   - `CheckOptionalConstraints`;
   - **schema validation of the emitted document — a JSON-Schema/OpenAPI
     schema validator, not Redocly's recommended ruleset.** This is settled,
     not a preference: Redocly's defaults flag `security-defined` on every
     operation (a direct consequence of auth being deferred, ADR 0005) and
     `operation-4xx-response` on `widgets.list`, which legitimately has no
     4xx. Using the lint ruleset means `make agents-docs` fails on day one
     for reasons the spec deliberately chose.

8. **`docs/agents.md`** — the source of truth for what an AGENTS.md must
   contain. Both language templates render their AGENTS.md from it: the
   three-layer architecture and its rules, the registry and how to add an
   operation, where widgets lives, the error taxonomy, and the explicit
   "don't do this" boundaries — service layer never imports `net/http` or
   FastAPI request types (and per ADR 0004, nothing outside
   `internal/transport/http/` does either); nothing outside `internal/config`
   reads an env var; nothing outside `internal/logging` imports structlog;
   nothing outside `internal/observability` constructs a metric; never label
   a metric with an unbounded value.

9. **Complete the registry-coverage test** from chunk 07: every registered
   operation is routable *and* appears in `/openapi.json` *and* in
   `/llms.txt`. This is the test that makes the design claim true.

10. **`CLAUDE.md` symlink** in generated services, verified present and
    pointing at AGENTS.md.

## Out of scope

MCP (deferred — see ADR 0004). Swagger UI or any HTML docs viewer. Running a
client generator in CI — ADR 0001 already verified `oapi-codegen` against the
3.0 copy and `openapi-typescript` against the 3.1 one; this chunk owes the
documents, not a generation pipeline.

## Deliverables

- `/openapi.json` (3.1) served by both generated services, plus a committed
  3.0.3 downgrade
- `cmd/docgen` (or its Python equivalent, which needs none — pydantic carries
  descriptions natively)
- `/llms.txt` served by both
- `make agents-docs` with its three checks and its staleness check, in both
- `docs/agents.md`, and AGENTS.md rendered from it in both templates
- Completed registry-coverage test

## Acceptance criteria

- `/openapi.json` reports `"openapi": "3.1.0"` and validates against an
  OpenAPI 3.1 schema validator in both languages.
- The committed 3.0.3 copy validates as 3.0.3, contains no
  `jsonSchemaDialect`, and its `exclusiveMinimum`/`exclusiveMaximum` are
  booleans.
- The operation lists in the Go and Python specs are identical — same
  operation IDs, paths, methods, and response codes. (ADR 0001's spike got
  five-for-five identical; three shipped operations should be easier.)
- No operation advertises `422`; a malformed body produces 400 problem+json
  in both languages and the spec says so.
- A named enum appears **once**, as its own component, referenced from every
  place it is used.
- Every field on the widgets types has a description in the Go document,
  harvested from its doc comment. Delete a doc comment, regenerate, and the
  generator reports the gap as a diagnostic.
- `map[string]any` (or its Python equivalent) is reported as a diagnostic,
  not silently emitted as an empty schema.
- Every registry operation appears in `/openapi.json` and `/llms.txt`;
  nothing appears in either that isn't in the registry.
- Adding an operation to the registry makes it appear in routes, OpenAPI,
  and `llms.txt` with **no other edit**. Demonstrate this — add one, show
  all three update, then revert.
- `make agents-docs` exits non-zero when generated output is stale.
  Demonstrate by editing a `##` comment without regenerating.
- Regenerating twice in a row produces no diff — output is deterministic.
- Neither template tree contains `openapi.json` or `llms.txt`; both
  generated services do, and both are committed by `_tasks`.
- `/openapi.json` still serves correctly after deleting the committed
  `openapi.json` from the generated service — the endpoint is
  registry-derived.
- Both generated AGENTS.md files have the same section structure and state
  the same boundaries.
- `scripts/parity.sh` gains check #6 (operation lists from both
  `/openapi.json` files) and an AGENTS.md structure diff.
- `scripts/verify-template.sh` fetches and validates both endpoints.

## Flag back before finishing

- **How the Python glue held up now that it drives a real document.** ADR
  0001 established that FastAPI *can* be driven from the registry, with ~150
  lines depending on FastAPI internals (`_make_endpoint`,
  `RequestValidationError`, `app.openapi`). A FastAPI major version can break
  that. If it needed more surface than the ADR budgeted, or a hook that looks
  more fragile than those three, say so — it is a real maintenance liability
  and Phase 2 should know its size.
- Whether the 3.0.3 downgrade stayed at ~20 lines. If it grew, it stopped
  being mechanical and became a second representation with its own bugs,
  which changes the calculus.
- Whether committing the 3.0 copy alongside the 3.1 one is the right call.
  ADR 0007 decided to commit `openapi.json` and `llms.txt`; it predates the
  downgrade requirement and does not mention a third file. If the drift
  check or the review burden argues against it, propose a superseding ADR
  rather than quietly gitignoring it.
- ADR 0007's committed-vs-gitignored call, if building the drift check
  changed your view of it. Note the honest cost it already accepts: every
  registry PR carries a second machine-generated diff, and reviewers learn to
  skip it.

*Settled, do not re-open:* 3.1 canonical with a 3.0.3 downgrade; the
build-time `go/ast` pass; schema validation rather than Redocly's ruleset;
committing the artifacts; never shipping them as template files. ADRs 0001
and 0007, approved. And the question this chunk used to lead with — whether
FastAPI could genuinely be driven from the registry — is answered: **yes,
with signature synthesis, specificity-ordered routes, and the 422 remap.**
