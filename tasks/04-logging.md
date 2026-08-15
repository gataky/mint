# 04 — Logging

**Spec:** § Logging — two-tier system
**Depends on:** 03 (config carries format and level). **ADR 0010 is binding
here** — it settles the Python library, the wire shape, the uvicorn problem,
and the two places the languages cannot match. ADR 0002 fixes the env var
names.
**Size:** M
**Standing rules:** [tasks/README.md](README.md#standing-rules--these-apply-to-every-chunk)

## Goal

One logger setup per language, two rendering tiers from the same call sites,
a reserved field set that both languages emit identically, and redaction that
works regardless of what a caller does.

ADR 0010 has already built this twice and byte-diffed the output — tier 2 came
out identical. Implement what it describes; the interesting work is in the
details it names, not in the shape.

## Do

1. **Reserved fields on every line, both tiers**, in this order:
   `timestamp`, `level`, `message`, `service`, `service_version`, `env`,
   `trace_id`, `span_id`. Note `message` — ADR 0010 § 3 adds it to the spec's
   list of seven, because structlog's `event` and slog's `msg` both have to
   be renamed to something and it belongs in the ratified table.

   Call sites cannot override them. `trace_id`/`span_id` are **omitted
   entirely** when there's no active span — never emitted empty, never
   fabricated. Guard on `SpanContext.is_valid` / `IsValid()`; an
   `INVALID_SPAN` in context must still produce no keys.

   Exact formats: `timestamp` is `%Y-%m-%dT%H:%M:%S.%fZ`, UTC, always six
   fractional digits (Go: `t.UTC().Format("2006-01-02T15:04:05.000000Z")`).
   `trace_id` is 32 hex, `span_id` is 16 hex.

2. **Key order is fixed**: the reserved block in the order above, then
   free-form keys in call order. **Nested objects are key-sorted in both
   languages** — Go's `encoding/json` sorts map keys, Python preserves
   insertion order, so Python sorts explicitly in the redaction processor.
   That sort is load-bearing; without it the two languages produce
   semantically identical, byte-different JSON.

   Corollary for Go: use `slog.Any` with a map for nested payloads, **not
   `slog.Group`**, whose order is declaration order.

3. **Tier 1 — console.** Human-readable, colorized. Default when
   `MINT_ENV=local` or unset, or `MINT_LOGGING__FORMAT=console`.

4. **Tier 2 — JSON.** One object per line, stable field names. Whenever
   `MINT_LOGGING__FORMAT=json` or `MINT_ENV` is non-local.

5. **Go**: `log/slog` behind a `mintHandler` wrapper (~120 lines) over
   `NewJSONHandler` (tier 2) and a colorizing handler (tier 1), selected at
   startup from config. `ReplaceAttr` renames `time`/`level`/`msg` and
   lowercases the level; `WithAttrs` carries `service`/`service_version`/
   `env`; `Handle` rebuilds the record so `trace_id`/`span_id` precede caller
   attrs, drops reserved keys, and redacts — recursing through `slog.Group`
   and through maps and slices held in `slog.KindAny` by reflection.

   **Tier 1 uses `lmittmann/tint`.** The spec assumes `slog.NewTextHandler`
   gives a "colorized human-readable console"; it does not — **`TextHandler`
   emits no ANSI at all.** ADR 0010 put the choice to the human and the colour
   dependency was approved. `tint` is a ~400-line `slog.Handler` used for
   tier 1 only. Pin it exactly and add it to ADR 0011's table — that table
   does not currently carry a `tint` row, so record the version you pin and
   say so in the handoff. Justify it in the generated README (chunk 10)
   alongside `structlog`.

   Tier 2 needs no dependency beyond `go.opentelemetry.io/otel/trace`.

6. **Python**: **`structlog`, pinned `26.1.0`** (ADR 0010). One processor
   chain whose last element is the tier renderer — nothing hand-formatted,
   and the two tiers differ only in that last element:

   - tier 2: `JSONRenderer(separators=(",", ":"), ensure_ascii=False)`. Those
     arguments are not cosmetic; they are what make the bytes match Go's
     `encoding/json`.
   - tier 1: `ConsoleRenderer(event_key="message", timestamp_key="timestamp",
     sort_keys=False)`.

   **Colour is decided by us, not by structlog.** `ConsoleRenderer`'s
   `colors` default only asks whether `colorama` is importable — it does not
   check `isatty()` and does not honour `NO_COLOR`, so it will happily write
   ANSI escapes into a redirected file. Pass
   `colors=stream.isatty() and not os.environ.get("NO_COLOR")`.

   structlog has **zero transitive runtime dependencies** and is pure Python;
   that is part of why it won, and worth stating in the README's dependency
   justification.

7. **Level vocabulary is slog's, in both languages: `debug | info | warn |
   error`, lowercase, and nothing else.** Python emits `warning` and
   `critical` natively, so the chain normalizes `warning→warn`,
   `critical→error`, `exception→error`. A service calling `logger.critical()`
   loses that distinction — `docs/logging.md` says so explicitly, because it
   is a real, deliberate loss.

8. **Boot uvicorn from the composition root, through our logging.** This is
   not in the spec and it is not optional: left alone, uvicorn calls
   `logging.config.dictConfig()` on its own `LOGGING_CONFIG` and attaches
   non-propagating handlers, so a "JSON-only" service emits nine plain-text
   lines and one JSON line per request lifecycle. **The `uvicorn` CLI cannot
   be fixed from inside the app** — `Config.configure_logging()` runs before
   the app module is imported.

   - `src/<pkg>/__main__.py` calls `uvicorn.run(app, log_config=None,
     access_log=False, …)`. `log_config=None` makes `configure_logging()`
     skip `dictConfig()` entirely, so our root handler survives and
     `uvicorn.error` propagates into it.

     **Chunk 06 will replace this call**, because ADR 0008 needs two
     `uvicorn.Server` instances built from one slice with
     `capture_signals` neutralized on each, and `uvicorn.run()` constructs
     and runs a single server internally with no handle on it. The two
     kwargs survive the move as `uvicorn.Config(...)` arguments. Write the
     `run()` call so that swap is a small one — don't build anything else
     around it.
   - `access_log=False` retires uvicorn's own access formatter; chunk 06's
     logging middleware emits a structured `http_request` line in its place.
   - `make run` invokes `python -m <pkg>` (already required by chunk 02).
   - The stdlib bridge is `structlog.stdlib.ProcessorFormatter` with
     `foreign_pre_chain` set to the **same** processor list, so third-party
     records (uvicorn, httpx, asyncio) get the reserved fields, the trace
     context and redaction too. `Started server process [20780]` must come
     out as a JSON object in the schema, not as `INFO:     …`.

9. **Trace correlation.** `trace_id` and `span_id` are pulled from the
   active OpenTelemetry span context by the handler/processor. Callers never
   pass them. Chunk 08 wires up real tracing — for now, integrate against the
   OTel API so that when a real provider is installed the IDs simply start
   appearing, with no logging changes. The processor reads whatever provider
   is installed, so this genuinely requires no chunk 08 edit; ADR 0010 says
   so and chunk 08 verifies it.

10. **Redaction in the handler/processor.** `key.lower() ∈ {password, token,
    secret, authorization, api_key}` → `"[REDACTED]"`, recursively through
    dicts, lists and tuples to depth 8, applied to the whole event dict
    before the renderer, in **both** tiers. **Exact match on the lowercased
    key, not substring** — `token_count` and `api_key_id` survive intact, and
    a test asserts that they do. The list is the same literal in both
    languages and lives in `docs/logging.md`.

11. **Free-form keys**: `snake_case`, documented, emitted after the reserved
    block in call order. **A call site that tries to set a reserved key has
    its value silently dropped and the reserved one kept** — in both
    languages (Go by skipping reserved keys while copying record attrs;
    Python via a `drop_reserved_keys` processor). Dropping rather than
    raising is deliberate: a logging call must never take down a request
    path. Ship a test that asserts the drop.

12. **Lint rule**: nothing outside `internal/logging` imports `structlog`
    (Python) or constructs a `slog.Handler` (Go) — the same grep-shaped rule
    as chunk 03's env var check. `internal/logging` is the only module that
    calls `configure()`.

13. **`docs/logging.md`** — the source of truth. The reserved field table from
    ADR 0010 § 3 with types and semantics, the two tiers and how they're
    selected, the redaction list, the free-form key convention, the four-level
    vocabulary and what `critical` maps to, and the two nested-ordering facts
    (Python sorts explicitly; Go uses `slog.Any` with a map, not
    `slog.Group`). `make parity` reads this file.

    Record the measured cost honestly, from ADR 0010: the chosen Python path
    is ~16 µs/line (62k lines/s) against Go's 1.28 µs — noise until roughly
    5k rps per process. `WriteLoggerFactory` is 1.7× faster and available as a
    documented knob for a service that becomes log-throughput-bound, at the
    cost of the one-configuration-point property.

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
- **Tier 2 is byte-identical between the two languages** for an equivalent
  set of call sites, normalizing only the timestamp and the randomly
  generated IDs. A `diff -u` of the two outputs is empty. ADR 0010's spike
  achieved this; anything less is a regression against proven ground.
- **Tier 1 parity is asserted on key *names* only.** Go's tier 1 and
  Python's tier 1 will not be byte-identical — different quoting, different
  nested-value rendering — and `scripts/parity.sh` must not pretend
  otherwise.
- Every reserved field is present on every line in both tiers, except
  `trace_id`/`span_id` which are absent — not empty — with no active span,
  and absent for an `INVALID_SPAN` too.
- Level normalization test: `logger.warning()` emits `"level":"warn"` and
  `logger.critical()` emits `"level":"error"` in Python; Go's `slog.Warn`
  emits `"level":"warn"`.
- Nested-object test: an equivalent nested payload produces the same key
  order in both languages. Remove the explicit Python sort and the test must
  fail.
- Redaction test: a caller logs `password="hunter2"` at a nested path and
  inside a list; it does not appear in either tier's output. `token_count`
  does appear.
- A caller attempting to set a reserved key has it dropped, identically in
  both languages, with no error raised.
- Booting the Python service produces **zero** `INFO:     …`-formatted
  lines: uvicorn's startup, access and shutdown lines all come out in the
  schema. Assert on the output of a real boot, not on configuration.
- `make run` for Python does not invoke the `uvicorn` CLI.
- `make lint` fails when `structlog` is imported outside `internal/logging`.
  Demonstrate, then revert.
- `scripts/parity.sh` gains check #5 from the spec (emitted keys vs
  `docs/logging.md`) and **fails** if you add a field to one language's
  logger and not the other. Demonstrate, then revert.

## Flag back before finishing

- The exact `lmittmann/tint` version you pinned, so ADR 0011's table can gain
  the row it's missing.
- Any reserved field that turned out to be awkward or expensive to populate
  in one language — better to cut it from the reserved set now than to have
  it silently missing later.
- If the `ProcessorFormatter` bridge costs more than the measured ~1.7×
  against `WriteLoggerFactory` in practice, say so; the ADR chose the bridge
  for the one-configuration-point property, and that trade is worth
  re-examining with real numbers rather than assumed ones.

*Settled, do not re-open:* structlog as the Python library (loguru, stdlib +
`python-json-logger`, and three others were built and lost on measured
grounds), the drop-don't-raise behaviour on reserved keys, and the
four-level vocabulary. ADR 0010, approved — including the colour dependency
for Go tier 1, which the human signed off explicitly.
