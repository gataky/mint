# 0012 — Pin `lmittmann/tint` v1.2.0 for Go tier-1 console logging

**Status:** accepted (2026-08-14)
**Date:** 2026-08-14
**Chunk:** 02 (recorded); implemented in 04
**Amends:** [0011](0011-pinned-toolchain-versions.md) (adds a row to the pin
table) · **Closes a gap in:** [0010](0010-use-structlog-for-python-logging.md)

## Context

[ADR 0010](0010-use-structlog-for-python-logging.md) found that the spec's
tier-1 requirement was unachievable as written: it asks for "human-readable,
colorized console output" and prescribes `slog.NewTextHandler`, which **emits
no ANSI at all**. 0010 put the choice to the human — accept an uncolored Go
tier 1, or take a colour dependency — and the dependency was approved, with
`uber-go/zap` named as an example.

Two loose ends followed. ADR 0011's pin table was written in parallel and has
no row for a colour library, and standing rule 5 makes that table *the* pin
list. And "zap or something like that" needs resolving into one library,
because zap and tint are not the same kind of change.

Re-verified on Go 1.26.6 before pinning:

```
$ go run .            # cat -v, so escapes are visible
time=2026-08-14T18:42:27.231-07:00 level=INFO msg="via TextHandler" port=8080
^[[2mAug 14 18:42:27.231^[[0m ^[[92mINF^[[0m via tint ^[[2mport=^[[0m8080
```

`TextHandler` produces plain logfmt with zero escape sequences. `tint`
produces `^[[2m` / `^[[92m`. The spec's claim was simply false, and it is
false in a way no configuration fixes.

## Decision

**Pin `github.com/lmittmann/tint` at `v1.2.0`** (released 2026-07-12), used
for **tier 1 only**. Tier 2 continues to use `slog.NewJSONHandler` behind the
`mintHandler` wrapper and needs no dependency beyond
`go.opentelemetry.io/otel/trace`.

Add the row to ADR 0011's pin table.

## Alternatives considered

**`uber-go/zap`, as the human suggested.** Rejected, and the reason is
specific rather than stylistic: zap is a complete logging framework, not a
`slog` handler. Adopting it replaces `log/slog` throughout, which discards
the result ADR 0010 spent its spike establishing — that Python's structlog
JSON output is **byte-identical** to Go's, measured by a normalized `diff -u`
against a `slog.JSONHandler` wrapper. That parity is the single hardest
property in the logging design and the only one `make parity` can assert
byte-for-byte. Trading it away to obtain colour in the tier nobody ships to
production is a bad exchange. zap also brings `go.uber.org/multierr` and
`go.uber.org/atomic`; tint brings nothing.

**Accept an uncolored Go tier 1.** Defensible — tier 1 is developer
ergonomics and never leaves a laptop — but the human was asked directly and
chose colour. Recorded here so the option isn't silently revisited.

**Write our own ~80-line colorizing `slog.Handler`.** Avoids the dependency,
but it is code every generated service inherits and nobody maintains, to
reimplement a well-scoped 400-line library. The dependency is the cheaper
liability.

## Consequences

**tint's defaults do not match Mint's reserved-field contract, and chunk 04
must override them.** The spike output shows `Aug 14 18:42:27.231` where the
schema requires `%Y-%m-%dT%H:%M:%S.%fZ` in UTC, and `INF` where the level
vocabulary is `debug | info | warn | error`. Configure `TimeFormat` and the
level renderer explicitly. This is readability, not parity — ADR 0010 already
established that tier 1 is compared on **key names only**, because tint and
structlog's `ConsoleRenderer` will never agree glyph-for-glyph — but a
generated service whose console timestamps disagree with its JSON timestamps
is exactly the kind of small incoherence that erodes trust in the template.

Every generated Go service gains one direct dependency, justified in its
README alongside structlog's.

`tint` is tier-1 only, so a service running with `MINT_LOGGING__FORMAT=json`
— every non-local environment — never executes it. The blast radius of a bug
in it is a developer's terminal.
