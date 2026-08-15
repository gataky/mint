# 05 — Error contract

**Spec:** § Architecture rules → Error contract
**Depends on:** 03. ADR 0001 fixes the `Problem` schema and makes the
category set feed the registry's `Errors` field; ADR 0004 fixes the shape of
the mapping table; ADR 0005 reserves the auth categories.
**Size:** S
**Standing rules:** [tasks/README.md](README.md#standing-rules--these-apply-to-every-chunk)

## Goal

The service layer can say "not found" / "invalid" / "conflict" / "internal"
without importing a single transport type, and the transport turns those into
identical `problem+json` responses in both languages.

Small chunk, but it lands before the HTTP server (chunk 06) because the
recovery middleware and every handler depend on it.

## Do

1. **Domain error taxonomy** in the service layer — sentinel errors in Go, an
   exception hierarchy in Python — with **identical categories in both
   languages**. At minimum: `invalid` (input failed business validation),
   `not_found`, `conflict`, `unauthorized`, `forbidden`, `internal`.
   Include `unauthorized`/`forbidden` even though auth is deferred; they
   cost nothing now and adding a category later means touching the mapping
   table, the docs, and both languages. ADR 0005 confirms this: when auth
   lands it adds one column to the mapping table and nothing else.

   **This category set is what ADR 0001's registry `Errors` field draws
   from** — `Errors: []ops.Category{ops.CatNotFound, ops.CatInvalid}` on an
   operation is how `widgets.get` declares its 404 in the generated OpenAPI.
   So the category type must be importable by the registry package without
   an import cycle, and the set must be closed and enumerable. Design for
   that now; chunk 07 depends on it.

2. **Wrapping.** A domain error can carry an underlying cause and structured
   detail without leaking either to the client. Go: `errors.Is`/`As`
   compatible. Python: exception chaining.

3. **Mapping table** owned by the transport: domain category → HTTP status.
   One table, one place, documented once. Structure it so a second transport
   later adds a **column** rather than inventing its own scheme — ADR 0004's
   spike added an MCP transport in 62 lines with a three-line column here and
   zero edits to `internal/apierror` itself. That is the shape to aim for.

4. **RFC 9457 `problem+json`** as the wire format: `type` (uri), `title`,
   `status` (integer), `detail`, `instance` (uri), plus a `trace_id`
   extension member so a user-reported error maps straight to a trace.
   Required: `type`, `title`, `status`. Content type
   `application/problem+json`. Byte-identical shape between languages.

   **`Problem` becomes a published OpenAPI component** (ADR 0001) — every
   operation's 4xx/5xx responses `$ref` it. Two consequences land here rather
   than in chunk 09: the type must be introspectable by the schema generator
   (in Python, a real pydantic `BaseModel`, because FastAPI only emits
   schemas for models it sees in a signature and chunk 09 has to inject this
   one into `components` by hand), and its field set must not drift from
   ADR 0001's component definition.

5. **The `invalid` category must be reachable from a framework-level
   validation failure.** FastAPI rejects a malformed body *before* the
   handler runs and returns `422` with its own `{"detail": [...]}` in
   `application/json`, where Go returns `400` problem+json — a wire-contract
   break between the two languages that no amount of handler discipline
   fixes. Chunk 07 installs the `RequestValidationError` handler that remaps
   it; this chunk must make sure the serializer can produce that body from
   outside a normal service-layer error path.

6. **The boundary rule**: driver errors, stack traces, and internal detail
   never cross the transport boundary. Log the detail at error level with
   the trace ID; return the category. `internal` in particular returns a
   generic message — the specifics go to the log, not the client.

7. **`internal/apierror/`** owns the taxonomy, the mapping table, and the
   `problem+json` serializer in both templates.

8. **`docs/architecture.md`** — write the error contract section: the
   category table with meanings and HTTP mappings, the wire format with an
   example body, and the boundary rule stated as a rule an agent can check
   itself against.

## Out of scope

Middleware (chunk 06) — this chunk provides what recovery and the error
handler will call, not the middleware itself. Validation logic for the
example resource (chunk 07).

## Deliverables

- `internal/apierror` in both templates, with tests
- The error contract section of `docs/architecture.md`

## Acceptance criteria

- Every category maps to exactly one HTTP status, identically in both
  languages.
- Serializing the same domain error in Go and in Python produces
  byte-identical JSON except for `instance` and `trace_id`.
- An error wrapping a simulated driver failure renders a generic client
  message; the driver detail appears in the log and nowhere in the response.
- `trace_id` is present in the body when a span is active and absent — not
  empty — when one isn't.
- Content type is `application/problem+json` on every error response.
- The category set is enumerable and importable by a package that knows
  nothing about HTTP — chunk 07's registry `Errors` field must be able to
  name a category without pulling in the transport.
- The `Problem` type's field set matches ADR 0001's published component
  exactly (`type`, `title`, `status`, `detail`, `instance`, `trace_id`, with
  the first three required).
- Tests cover every category in both languages, with matching test names per
  the shared conventions.

## Flag back before finishing

- Any category that felt wrong or missing once you wrote the mapping table.
  This is the cheapest moment in the whole project to change the taxonomy —
  and note that chunk 07 freezes the registry shape that consumes it, so
  after that a new category is a coordinated change.
- Whether `unauthorized`/`forbidden` existing while auth is deferred creates
  any confusion worth resolving with a comment in the code. ADR 0005 is the
  thing to point that comment at.
