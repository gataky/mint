# 04 — Logging

**Spec:** § Logging — two-tier system
**Depends on:** 03 (config carries format and level); ADR 0010 for the
Python library choice
**Size:** M
**Standing rules:** [tasks/README.md](README.md#standing-rules--these-apply-to-every-chunk)

## Goal

One logger setup per language, two rendering tiers from the same call sites,
a reserved field set that both languages emit identically, and redaction that
works regardless of what a caller does.

## Do

1. **Reserved fields on every line, both tiers**: `timestamp`, `level`,
   `service`, `service_version`, `env`, `trace_id`, `span_id`. Call sites
   cannot override them. `trace_id`/`span_id` are **omitted entirely** when
   there's no active span — never emitted empty, never fabricated.

2. **Tier 1 — console.** Human-readable, colorized. Default when `ENV=local`
   or unset, or `LOG_FORMAT=console`.

3. **Tier 2 — JSON.** One object per line, stable field names. Whenever
   `LOG_FORMAT=json` or `ENV` is non-local.

4. **Go**: `log/slog` with `NewTextHandler` (tier 1) and `NewJSONHandler`
   (tier 2), selected at startup from config. Reserved fields come from a
   custom handler wrapper, not from every call site.

5. **Python**: the library chosen in ADR 0010, configured so one set of call
   sites renders both tiers. No hand-rolled formatters.

6. **Trace correlation.** `trace_id` and `span_id` are pulled from the
   active OpenTelemetry span context by the handler. Callers never pass
   them. Chunk 08 wires up real tracing — for now, integrate against the
   OTel API so that when a real provider is installed the IDs simply start
   appearing, with no logging changes.

7. **Redaction in the handler.** A documented key list (`password`, `token`,
   `secret`, `authorization`, `api_key`, …) is redacted at render time, in
   both tiers, for both top-level and nested keys. This is a property of the
   handler, not of call-site discipline.

8. **Free-form keys**: `snake_case`, documented. Reserved keys are rejected
   or ignored if a call site tries to set one — pick one behavior and make
   both languages do the same thing.

9. **`docs/logging.md`** — the source of truth. The reserved field table with
   types and semantics, the two tiers and how they're selected, the
   redaction list, the free-form key convention. `make parity` reads this
   file.

## Out of scope

Real tracing setup and span creation (chunk 08). Request logging middleware
(chunk 06) — this chunk builds the logger, not the middleware that uses it.

## Deliverables

- `internal/logging` in both templates, with tests
- `docs/logging.md`
- A parity check that boots each generated service and diffs emitted log
  keys against the table in `docs/logging.md`

## Acceptance criteria

- Same call site produces console output in tier 1 and a single-line JSON
  object in tier 2, in both languages.
- Every reserved field is present on every line in both tiers, except
  `trace_id`/`span_id` which are absent — not empty — with no active span.
- A JSON log line from the Go service and one from the Python service, for
  an equivalent event, have identical key sets.
- Redaction test: a caller logs `password="hunter2"` at a nested path; it
  does not appear in either tier's output.
- A caller attempting to set a reserved key gets the documented behavior,
  identically in both languages.
- `scripts/parity.sh` gains check #5 from the spec (emitted keys vs
  `docs/logging.md`) and **fails** if you add a field to one language's
  logger and not the other. Demonstrate, then revert.

## Flag back before finishing

- The Python library decision if the spike disagreed with ADR 0010 once it
  met the redaction and reserved-field requirements.
- Any reserved field that turned out to be awkward or expensive to populate
  in one language — better to cut it from the reserved set now than to have
  it silently missing later.
