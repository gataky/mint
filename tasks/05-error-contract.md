# 05 — Error contract

**Spec:** § Architecture rules → Error contract
**Depends on:** 03
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
   table, the docs, and both languages.

2. **Wrapping.** A domain error can carry an underlying cause and structured
   detail without leaking either to the client. Go: `errors.Is`/`As`
   compatible. Python: exception chaining.

3. **Mapping table** owned by the transport: domain category → HTTP status.
   One table, one place, documented once. Structure it so a second transport
   later adds a column rather than inventing its own scheme.

4. **RFC 9457 `problem+json`** as the wire format: `type`, `title`,
   `status`, `detail`, `instance`, plus a `trace_id` extension member so a
   user-reported error maps straight to a trace. Content type
   `application/problem+json`. Byte-identical shape between languages.

5. **The boundary rule**: driver errors, stack traces, and internal detail
   never cross the transport boundary. Log the detail at error level with
   the trace ID; return the category. `internal` in particular returns a
   generic message — the specifics go to the log, not the client.

6. **`internal/apierror/`** owns the taxonomy, the mapping table, and the
   `problem+json` serializer in both templates.

7. **`docs/architecture.md`** — write the error contract section: the
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
- Tests cover every category in both languages, with matching test names per
  the shared conventions.

## Flag back before finishing

- Any category that felt wrong or missing once you wrote the mapping table.
  This is the cheapest moment in the whole project to change the taxonomy.
- Whether `unauthorized`/`forbidden` existing while auth is deferred creates
  any confusion worth resolving with a comment in the code.
