# 0010 — Use structlog for Python logging, and boot uvicorn through it

**Status:** accepted (2026-08-14)
**Date:** 2026-08-14
**Chunk:** [01](../../tasks/01-decisions.md) (implemented by [04](../../tasks/04-logging.md))

## Context

`prompt.md` § "Logging — two-tier system" tells the Go side exactly what to
use (`log/slog`, `NewTextHandler` / `NewJSONHandler`) and tells the Python
side only to "pick one library that cleanly supports both a human console
renderer and a JSON renderer from the same call sites (e.g. `structlog`)".
That library has to satisfy five things at once, and the last one is what
actually decides it:

1. Two renderers, one set of call sites, **no hand-rolled formatters**.
2. Seven reserved fields on every line, not settable by call sites.
3. `trace_id` / `span_id` lifted from the active OTel span context
   automatically, and **omitted entirely** when there is no valid span.
4. Redaction of a documented key list **at the handler/processor level**,
   including nested keys, in both tiers.
5. The resulting shape has to be reproducible by Go's `log/slog`, because
   `make parity` check #5 diffs the two languages' emitted keys.

A spike was built rather than argued: a full Python implementation
(structlog), a full Go implementation (`log/slog` + a handler wrapper), a
best-effort implementation of each losing candidate, a FastAPI service run
under uvicorn both ways, an assertion suite, and a byte-diff of the two
languages' tier-2 output. Everything quoted below is real captured output.

### What the spike proved

**Tier 2 (JSON) is byte-identical between Python and Go.** Normalizing only
the timestamp and the randomly-generated IDs, `diff -u` of the two
implementations' output is empty:

```
$ ./paritycheck.sh
PARITY OK: tier 2 is byte-identical (Python structlog == Go log/slog)
```

Python (structlog), `LOG_FORMAT=json`:

```json
{"timestamp":"2026-08-15T00:49:18.460392Z","level":"info","message":"service started","service":"widget-api","service_version":"1.4.2","env":"prod","port":8080,"admin_port":9080}
{"timestamp":"2026-08-15T00:49:18.460876Z","level":"info","message":"handled request","service":"widget-api","service_version":"1.4.2","env":"prod","trace_id":"d0d6cc0a5825d8a85d1a1a839c3d4ef1","span_id":"a8878d45ac678dbd","http_method":"GET","route":"/widgets/{id}","status":200}
{"timestamp":"2026-08-15T00:49:18.460929Z","level":"warn","message":"auth failed","service":"widget-api","service_version":"1.4.2","env":"prod","trace_id":"d0d6cc0a5825d8a85d1a1a839c3d4ef1","span_id":"a8878d45ac678dbd","password":"[REDACTED]","user":{"credentials":{"api_key":"[REDACTED]","token":"[REDACTED]"},"email":"a@b.com","id":42},"upstream_calls":[{"headers":{"authorization":"[REDACTED]"},"url":"https://x/y"}],"Authorization":"[REDACTED]","token_count":1234}
{"timestamp":"2026-08-15T00:49:18.460977Z","level":"error","message":"boom","service":"widget-api","service_version":"1.4.2","env":"prod","trace_id":"d0d6cc0a5825d8a85d1a1a839c3d4ef1","span_id":"a8878d45ac678dbd","request_id":"r-1"}
{"timestamp":"2026-08-15T00:49:18.461016Z","level":"info","message":"shutdown complete","service":"widget-api","service_version":"1.4.2","env":"prod","drain_ms":12}
```

Go (`log/slog`), same five call sites:

```json
{"timestamp":"2026-08-15T00:49:18.757204Z","level":"info","message":"service started","service":"widget-api","service_version":"1.4.2","env":"prod","port":8080,"admin_port":9080}
{"timestamp":"2026-08-15T00:49:18.757218Z","level":"info","message":"handled request","service":"widget-api","service_version":"1.4.2","env":"prod","trace_id":"207903a762d1a23bbcfcbfff781a3521","span_id":"eabf1ccc774c271b","http_method":"GET","route":"/widgets/{id}","status":200}
{"timestamp":"2026-08-15T00:49:18.757222Z","level":"warn","message":"auth failed","service":"widget-api","service_version":"1.4.2","env":"prod","trace_id":"207903a762d1a23bbcfcbfff781a3521","span_id":"eabf1ccc774c271b","password":"[REDACTED]","user":{"credentials":{"api_key":"[REDACTED]","token":"[REDACTED]"},"email":"a@b.com","id":42},"upstream_calls":[{"headers":{"authorization":"[REDACTED]"},"url":"https://x/y"}],"Authorization":"[REDACTED]","token_count":1234}
```

**Tier 1 (console), same Python call sites**, colorized on a TTY (ANSI
stripped here because the capture was piped):

```
2026-08-15T00:49:18.577144Z [info     ] service started                service=widget-api service_version=1.4.2 env=local port=8080 admin_port=9080
2026-08-15T00:49:18.577647Z [info     ] handled request                service=widget-api service_version=1.4.2 env=local trace_id=cb79f5463f18c3ba… span_id=29cee9c048ba4a5a http_method=GET route=/widgets/{id} status=200
2026-08-15T00:49:18.577707Z [warn     ] auth failed                    service=widget-api service_version=1.4.2 env=local trace_id=cb79f5463f18c3ba… span_id=29cee9c048ba4a5a password=[REDACTED] user={'credentials': {'api_key': '[REDACTED]', 'token': '[REDACTED]'}, 'email': 'a@b.com', 'id': 42} upstream_calls=[{'headers': {'authorization': '[REDACTED]'}, 'url': 'https://x/y'}] Authorization=[REDACTED] token_count=1234
```

With colors on (`| cat -v`, timestamp dim, level green/yellow/red, keys cyan,
values magenta):

```
^[[2m2026-08-15T00:48:43.363283Z^[[0m [^[[32m^[[1minfo     ^[[0m] ^[[1mservice started               ^[[0m ^[[36mservice^[[0m=^[[35mwidget-api^[[0m …
```

The two tiers come from the *same* processor chain; only the final element
differs (`JSONRenderer` vs `ConsoleRenderer`). Nothing is hand-formatted.

### Requirement 3 and 4 proof

These are where libraries fall down, so they were asserted rather than
eyeballed (`test_mintlog.py` in the spike):

```
OK  no active span -> trace_id/span_id absent (not empty, not faked)
OK  active span -> 32-hex trace_id + 16-hex span_id, caller passed nothing
OK  INVALID_SPAN in context -> still omitted (is_valid guards it)
OK  redaction: top level, 4-deep nesting, inside lists, case-insensitive,
    in BOTH tiers, and non-listed lookalike keys survive
OK  call-site attempts to set reserved keys are dropped; free-form kept
OK  key order = reserved schema order, then call order (matches slog)
OK  log.exception -> level=error, traceback under `exception`, still redacted

ALL ASSERTIONS PASSED
```

The two processors that do it are ~15 lines each and are the whole of the
mechanism — there is no call-site discipline anywhere:

```python
def add_otel_context(logger, name, ed):
    ctx = trace.get_current_span().get_span_context()
    if ctx.is_valid:                       # False for INVALID_SPAN_CONTEXT
        ed["trace_id"] = trace.format_trace_id(ctx.trace_id)
        ed["span_id"] = trace.format_span_id(ctx.span_id)
    return ed                              # otherwise: keys never appear

def redact(logger, name, ed):              # recurses dicts, lists, tuples
    return _redact(ed)                     # key.lower() in REDACT_KEYS -> "[REDACTED]"
```

Note in the tier-2 sample above: `password`, `user.credentials.token`,
`user.credentials.api_key`, `upstream_calls[0].headers.authorization` and
`Authorization` (capitalised) are all `[REDACTED]`, while `token_count`
— a lookalike that is not on the list — survives intact.

### The uvicorn problem (not in the spec, but real)

FastAPI runs under uvicorn, which calls `logging.config.dictConfig()` on its
own `LOGGING_CONFIG` and attaches its own handlers to `uvicorn`,
`uvicorn.error` and `uvicorn.access`, all with `propagate: False`. Left
alone, a "JSON-only" service emits nine plain-text lines and one JSON line
per request lifecycle — captured from the spike:

```
INFO:     Started server process [20459]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8731 (Press CTRL+C to quit)
{"timestamp":"…","level":"info","message":"fetching widget","service":"widget-api",…}
INFO:     127.0.0.1:63544 - "GET /widgets/abc123 HTTP/1.1" 200 OK
INFO:     Shutting down
…
```

That fails the two-tier requirement in practice: the access log and the
lifecycle log are unparseable by the aggregator and carry none of the seven
reserved fields.

Launching via the `uvicorn` CLI does **not** fix it even when the app module
configures logging at import time, because `Config.configure_logging()` runs
*before* the app is imported and installs non-propagating handlers that our
root handler never sees. Verified:

```
$ uv run uvicorn uvi_demo:app --port 8734
INFO:     Started server process [21577]                       <- uvicorn's format
{"timestamp":"…","message":"http_request","route":"/widgets/{widget_id}",…}   <- ours
INFO:     127.0.0.1:63553 - "GET /widgets/abc123 HTTP/1.1" 200 OK   <- duplicate, wrong format
```

## Decision

**Use `structlog` (pinned `26.1.0`) for Python logging**, configured as a
single processor chain whose last element is the tier renderer, and **boot
uvicorn from the service's own composition root with `log_config=None` and
`access_log=False`**, emitting the access log from our own middleware.

Concretely:

1. **One chain, two renderers.** `internal/logging` builds one list of
   processors and appends either
   `structlog.processors.JSONRenderer(separators=(",", ":"), ensure_ascii=False)`
   (tier 2) or `structlog.dev.ConsoleRenderer(event_key="message",
   timestamp_key="timestamp", sort_keys=False)` (tier 1), chosen from config.
   The `separators` / `ensure_ascii` arguments are not cosmetic: they are what
   make the bytes match Go's `encoding/json`.

2. **Reserved fields are processors, not call-site arguments.** A
   `drop_reserved_keys` processor deletes any of the eight reserved keys a
   call site supplies, then binder processors set the real values. **Behavior
   on conflict is: silently drop the caller's value, keep the reserved one**
   (Go does the same, by skipping reserved keys while copying record attrs).
   Dropping rather than raising is deliberate — a logging call must never
   take down a request path — and chunk 04 ships a test that asserts it.

3. **The canonical wire shape** — proposed here, ratified in
   `docs/logging.md` by chunk 04:

   | key | notes |
   | --- | --- |
   | `timestamp` | `%Y-%m-%dT%H:%M:%S.%fZ`, UTC, always 6 fractional digits. Go: `t.UTC().Format("2006-01-02T15:04:05.000000Z")`. |
   | `level` | lowercase, **`debug` \| `info` \| `warn` \| `error` only** |
   | `message` | the event text (structlog `event` and slog `msg` are both renamed to it) |
   | `service`, `service_version`, `env` | handler-level attrs |
   | `trace_id` (32 hex), `span_id` (16 hex) | present only when the span context is valid |
   | free-form | `snake_case`, in call order, after the reserved block |

   Key order is fixed: the reserved block in the order above, then free-form
   keys in call order. Nested objects are key-sorted in both languages
   (Python sorts them explicitly; Go's `encoding/json` sorts map keys).

4. **Redaction rule**: `key.lower() ∈ {password, token, secret,
   authorization, api_key}` → `"[REDACTED]"`, recursively through dicts and
   lists to depth 8, applied to the whole event dict before the renderer.
   Exact match on the lowercased key, not substring — so `token_count` and
   `api_key_id` are not redacted. The list lives in `docs/logging.md` and is
   the same literal in both languages.

5. **Colour is decided by us, not by structlog.** `ConsoleRenderer`'s
   `colors` default only asks whether `colorama` is importable — it does
   **not** check `isatty()` and does **not** honour `NO_COLOR`, so it will
   happily write ANSI escapes into a redirected file. `internal/logging`
   passes `colors=stream.isatty() and not os.environ.get("NO_COLOR")`.

6. **uvicorn**: the generated service's entrypoint is
   `src/<pkg>/__main__.py`, which calls
   `uvicorn.run(app, log_config=None, access_log=False, …)`. `log_config=None`
   makes `Config.configure_logging()` skip `dictConfig()` entirely
   (`uvicorn/config.py:384`), so the root handler installed by
   `internal/logging` survives and `uvicorn.error` propagates into it.
   `access_log=False` retires uvicorn's `%(client_addr)s - "%(request_line)s"`
   formatter, and chunk 06's logging middleware emits a structured
   `http_request` line in its place. `make run` therefore invokes
   `python -m <pkg>`, never the `uvicorn` CLI — which also mirrors Go, where
   `cmd/<service>/main.go` is the only entrypoint.

   The stdlib bridge is `structlog.stdlib.ProcessorFormatter` with
   `foreign_pre_chain` set to the *same* processor list, so third-party
   records (uvicorn, httpx, asyncio) get the reserved fields, the trace
   context and redaction too. Result, tier 2:

   ```json
   {"timestamp":"2026-08-15T00:46:27.372629Z","level":"info","message":"Started server process [20780]","service":"widget-api","service_version":"1.4.2","env":"prod"}
   {"timestamp":"2026-08-15T00:46:27.373265Z","level":"info","message":"Application startup complete.","service":"widget-api","service_version":"1.4.2","env":"prod"}
   {"timestamp":"2026-08-15T00:46:27.410423Z","level":"info","message":"fetching widget","service":"widget-api","service_version":"1.4.2","env":"prod","trace_id":"5c301287277bcd932ae1081c627bd566","span_id":"42497db84bb4eb6c","widget_id":"abc123"}
   {"timestamp":"2026-08-15T00:46:27.410614Z","level":"info","message":"http_request","service":"widget-api","service_version":"1.4.2","env":"prod","trace_id":"5c301287277bcd932ae1081c627bd566","span_id":"42497db84bb4eb6c","http_method":"GET","route":"/widgets/{widget_id}","status":200,"duration_ms":0.573,"client_ip":"127.0.0.1","authorization":"[REDACTED]"}
   {"timestamp":"2026-08-15T00:46:27.576177Z","level":"info","message":"Finished server process [20780]","service":"widget-api","service_version":"1.4.2","env":"prod"}
   ```

   Every line, including uvicorn's own, is one JSON object in the schema; the
   access line carries the **route template** `/widgets/{widget_id}` (not the
   concrete path — the metrics cardinality rule applies to logs too) and its
   `authorization` value was redacted by the processor even though the
   middleware passed the raw header in. The identical run with
   `LOG_FORMAT=console` produces the colorized tier-1 form of all ten lines.

7. **Go must match by construction, and does.** The Go template gets a
   `mintHandler` wrapping `slog.NewJSONHandler` / `slog.NewTextHandler`:
   `ReplaceAttr` renames `time`/`level`/`msg` and lowercases the level;
   `WithAttrs` carries `service`/`service_version`/`env`; `Handle` rebuilds
   the record so `trace_id`/`span_id` (from
   `trace.SpanContextFromContext(ctx)`, guarded by `IsValid()`) precede
   caller attrs, drops reserved keys, and redacts — recursing through
   `slog.Group`, and through maps/slices held in `slog.KindAny` by
   reflection. That handler is ~120 lines and needs no dependency beyond
   `go.opentelemetry.io/otel/trace`.

## Alternatives considered

**loguru.** It is genuinely good at requirements 2, 3 and 4 — a
`logger.configure(patcher=…)` runs after `bind()`, so reserved fields,
trace context and recursive redaction all worked in the spike. It loses on
1 and 5. Its only non-hand-rolled JSON renderer is `serialize=True`, whose
shape is produced by a hardcoded `Handler._serialize_record` static method
with no hook:

```json
{"text": "auth failed\n",
 "record": {"elapsed": {...}, "exception": null,
            "extra": {"password": "[REDACTED]", "service": "widget-api",
                      "trace_id": "aec8b1a6…", "span_id": "e568dc64…"},
            "file": {...}, "function": "<module>", "level": {"icon": "⚠️", "name": "WARNING", "no": 30},
            "line": 52, "module": "alt_loguru", "process": {...}, "thread": {...},
            "time": {"repr": "…", "timestamp": 1786754698.286342}}}
```

The seven reserved fields end up nested under `record.extra`, `level` is an
object, `time` is an object, and there is no supported way to flatten any of
it. Matching that in Go would mean building the envelope by hand on the Go
side too — and getting a flat shape out of loguru means passing a
`sink=lambda msg: …json.dumps(…)` callable, which *is* the hand-rolled
formatter the spec rules out. It also intercepts stdlib logging only via a
propagation shim, so the uvicorn story is worse, not better.

**stdlib `logging` + `python-json-logger` + `colorlog`.** Zero new concepts
and the JSON tier is respectable. It fails requirement 1 outright: the two
tiers do not carry the same information from the same call site, because a
`logging.Formatter` format string has no placeholder for "every extra the
caller passed". Same two call sites, both tiers:

```
tier 2: {"timestamp": "…", "level": "WARNING", "message": "auth failed", "service": "widget-api", …, "password": "[REDACTED]", "user": {"credentials": {"token": "[REDACTED]", …}}, "trace_id": "32c372e8…"}
tier 1: 2026-08-14 17:45:31,685 WARNING  auth failed service=widget-api service_version=1.4.2 env=prod
```

Every free-form key — `port`, `admin_port`, `password`, `user` — is silently
gone in tier 1. Recovering them means subclassing `Formatter` and iterating
`record.__dict__`, i.e. hand-rolling. Two further problems: `trace_id` and
`span_id` land *after* the free-form keys (the format string can't order a
conditionally-present field), so key order is unstable and un-diffable
against Go; and `asctime` cannot produce microseconds via `datefmt` without,
again, a custom formatter. It also needs *two* third-party packages to
structlog's one.

**Go-style: `slog`-alike in Python (`logging` + `orjson` + a custom
handler).** Rejected on the spec's own terms — "no hand-rolled formatters" —
and it would put the most parity-critical code in the template in the one
place with no upstream test suite behind it.

**`eliot` / `logbook` / `picologging`.** `eliot` models actions and
causality rather than lines, which is a different (and larger) idea than the
spec's flat schema; `logbook` is effectively unmaintained; `picologging` is
a stdlib-`logging` accelerator, so it inherits the tier-1 failure above and
adds a C extension to a template that otherwise has none.

**structlog with `WriteLoggerFactory` instead of the stdlib bridge.**
Considered and rejected as the *default*: it is 1.7× faster (below), but it
bypasses `logging`, so uvicorn's and httpx's records need a second sink and
the "one configuration point" property is lost. It stays available as a
documented knob for a service that becomes log-throughput-bound.

## Consequences

**What this makes easy.** One `configure()` call at startup owns every log
line the process emits, ours and third-party. Adding a field to the schema
is one processor edit in each language. Call sites are
`log.info("event", key=value)` in Python and `log.InfoContext(ctx, "event",
"key", value)` in Go — same information, same output. Chunk 06's middleware
gets `contextvars`-based request-scoped binding
(`structlog.contextvars.bind_contextvars(request_id=…)`), verified in the
spike to survive into the endpoint through `BaseHTTPMiddleware`.

**Dependency cost.** One package, `structlog`, which has **zero transitive
runtime dependencies** (`uv pip show structlog` → `Requires:` empty) and is
pure Python. That is the cheapest of the candidates: loguru is one package
with a Windows-only dep, the stdlib route is two.

**Performance cost, measured** (50k lines, M5 Pro, output to a buffer):

| path | per line | throughput |
| --- | --- | --- |
| structlog → stdlib `ProcessorFormatter` (chosen) | 16.2 µs | 62k lines/s |
| …inside an active span (adds the OTel lookup) | 18.2 µs | 55k lines/s |
| structlog → `WriteLogger` (bypasses stdlib) | 9.3 µs | 108k lines/s |
| stdlib `logging`, no structure at all | 2.9 µs | 344k lines/s |
| Go `log/slog` + `mintHandler` | 1.28 µs | 780k lines/s, 15 allocs/op |

The chosen path costs ~5.5× a bare `logging.info()` and ~12× the Go
equivalent. At one access-log line plus a handful of application lines per
request that is noise until roughly 5k rps per process; it is written down
here so nobody has to rediscover it during an incident.

**What this makes hard — and where Go cannot match.** Three honest gaps:

- **Tier 1 is not, and will not be, byte-identical across languages.**
  `slog.NewTextHandler` emits uncoloured logfmt and quotes differently
  (`message="auth failed"`), and it renders a nested map as
  `user="map[credentials:map[api_key:[REDACTED] …]]"` where structlog renders
  a Python repr. **The spec's assumption that `slog.NewTextHandler` gives a
  "colorized human-readable console" is wrong — `TextHandler` emits no ANSI
  at all.** Options for chunk 04, in preference order: (a) accept uncoloured
  logfmt for Go tier 1 and amend the spec's wording; (b) add
  `lmittmann/tint` (a ~400-line `slog.Handler`) to the Go template purely for
  tier 1. This needs a call from the human — it is the one place the spec's
  two languages genuinely cannot be made identical for free.
  **`make parity` must therefore assert tier 2 only**, and assert tier 1 only
  to the extent that the same key *names* appear.

- **`level` values had to be forced into slog's vocabulary.** Python emits
  `warning` / `critical` natively; slog has `WARN` and no `critical`. The
  chain normalizes `warning→warn`, `critical→error`, `exception→error`. Any
  service using `logger.critical()` loses that distinction in the logs; the
  canonical set is four levels and `docs/logging.md` says so.

- **Nested-object key order needed a deliberate fix.** Go's `encoding/json`
  sorts map keys; Python preserves insertion order. Without the explicit
  sort in the redaction processor the two languages produce semantically
  identical but byte-different JSON. That sort is load-bearing, and the Go
  template must use `slog.Any` with a map (not `slog.Group`, whose order is
  declaration order) for nested payloads. Both facts belong in
  `docs/logging.md` next to the schema.

**What reversing it costs.** The call-site API (`log.info("event",
key=value)`) is structlog's `BoundLogger` API. Swapping libraries later
means touching every call site in every generated service, not just
`internal/logging` — the same exposure the Go side has to `slog`. The seam
that limits the damage is that `internal/logging` is the only module that
imports structlog directly and the only one that calls `configure()`; the
`make lint` "nothing outside `internal/config` reads an env var" check
should gain a sibling for "nothing outside `internal/logging` imports
structlog".

**Follow-ups this creates.** Chunk 04 ratifies the field table above in
`docs/logging.md` (including the `message` key, which `prompt.md`'s list of
seven does not name) and adds parity check #5. Chunk 06 owns the
`http_request` access-log line and the reserved slot ordering. Chunk 08
replaces the spike's manual span with real OTel ASGI instrumentation — no
logging change is needed, since `add_otel_context` already reads whatever
provider is installed.

**Spike location.** `scratchpad/adr-0010/` — `mintlog.py` (the candidate
`internal/logging`), `goparity/main.go` (the Go counterpart),
`test_mintlog.py` (the assertions quoted above), `paritycheck.sh` (the
byte-diff), `uvi_demo.py` + `run_uvi.sh` (the uvicorn experiment),
`alt_loguru.py` and `alt_stdlib.py` (the losing candidates), `bench.py`.
Versions exercised: CPython 3.14.6, uv 0.12.5, structlog 26.1.0,
opentelemetry-api/sdk 1.44.0, fastapi 0.141.1, uvicorn 0.52.3, Go 1.26.5,
`go.opentelemetry.io/otel` 1.44.0.
