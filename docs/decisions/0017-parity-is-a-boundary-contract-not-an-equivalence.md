# 0017 — Parity is a contract at the boundaries, not an equivalence everywhere

**Status:** accepted (2026-08-14)
**Date:** 2026-08-14
**Chunk:** 03 → 04 boundary
**Supersedes:** the scope of the spec's second principle as applied to
cross-language parity. It does **not** supersede the principle itself —
mechanical guarantees still beat aspirational ones; this narrows *what* gets
guaranteed.

## Context

The spec asked for the *experience* of building, running and testing a
generated service to feel identical regardless of language. That is a
statement about the developer's command surface. In practice it was
implemented as "the two services must be identical in as many observable
respects as possible," and the cost compounded with every chunk:

- **Config (chunk 03).** `duration.py` is a digit-for-digit port of Go's
  `ParseDuration` and `Duration.String`. Python has `timedelta`. The port
  exists so that two strings match in a `diff`.
- **Logging (chunk 04, unbuilt).** ADR 0010 specified tier-2 output
  byte-identical across languages, requiring `separators=(",", ":")`,
  `ensure_ascii=False`, and explicit nested-key sorting in Python because
  Go's `encoding/json` sorts map keys. None of that is visible to a log
  aggregator, which parses JSON.
- **Metrics (chunk 08, unbuilt).** ~60 lines of hand-written middleware per
  language, because neither client library's defaults could be reconciled.
- **`make parity`.** Eleven checks, three of which compared internal
  structure — directory trees, file trees, byte-identical `make config`
  output — that no consumer outside the service ever sees.

The tax is real and it lands on whichever language does not do the thing
natively. Meanwhile the checks themselves proved unusually defect-prone:
four of the eleven had bugs, and two of those **passed green** while
comparing two identically-broken outputs.

## Decision

**Parity is required only where something outside the service consumes the
thing.** Everywhere else, each language does what is idiomatic for it.

**Contracts — identical, and mechanically checked:**

| what | the external consumer that breaks otherwise |
| --- | --- |
| Makefile target names and their semantics | developers and coding agents moving between services; this is the "feels identical" the spec actually wanted |
| Metric names and label **keys** | Prometheus, and any dashboard or alert spanning more than one service |
| Log field **names** | log aggregator queries that span services |
| Config precedence and env var names | runbooks, and a ConfigMap `envFrom`-ed by several services (ADR 0002) |

**Not contracts — idiomatic per language, and not checked:**

internal directory and file layout · error message wording · byte-level
output formatting · JSON key order, separators and whitespace · duration and
number formatting · test structure beyond naming conventions · the shape of
internal types.

The distinguishing question is: **if these two differed, what outside the
service would break?** If the answer is "nothing, but a diff would fail,"
the diff is the problem.

`{"level":"info","service":"x"}` and `{ "level": "info", "service": "x" }`
are now equally correct. Same keys; formatting free.

## Alternatives considered

**Keep full parity.** It does buy something real: a class of bug where one
language quietly diverges is caught immediately, and the discipline forced
several genuine findings (`promhttp` panicking on a `route` label was found
because the outputs had to match). Rejected because the cost is unbounded
and grows per chunk, while the benefit is concentrated in a few boundaries
that can be checked directly and much more cheaply.

**Drop parity entirely and rely on `make verify`.** Simplest, and verify does
prove each service works. Rejected because it gives up the fleet-wide
contracts: two services emitting `http_requests_total` and
`http_server_requests_total` both work perfectly and cannot be graphed
together. That failure is invisible to any per-service test.

**Keep the checks but downgrade failures to warnings.** Rejected on the
spec's own second principle — a warning in a passing build is read once, by
nobody. A check either matters enough to fail the build or should not exist.

## Consequences

`make parity` drops from eleven checks to eight, and is reorganised into
**contracts** (things with an external consumer) and **template hygiene**
(the templates being well-formed at all — unrendered delimiters, generated
artifacts committed where they shouldn't be). The hygiene checks were never
parity checks; grouping them honestly makes the distinction visible in the
output.

Dropped: package directory sets, normalized file trees, byte-identical
`make config` output. `make config` is still asserted to **succeed** in both,
because a broken `--print-config` is a real defect.

**`make verify` becomes the more important harness.** It proves each service
actually works rather than that two of them match. The trade is deliberate:
when the languages diverge behaviorally we now find out from a failing
verify, not from a diff — later, and with a less precise signal.

**Existing over-built code is debt, not an emergency.** `duration.py`'s
digit-for-digit port is tested and working; it should be simplified to
`timedelta` when that file is next touched, not churned now. Chunk 04's
byte-identity requirement is unbuilt and is cancelled outright — that is the
main saving this ADR buys, and it is why the decision lands before chunk 04
rather than after.

**A residual risk worth naming.** Loosening formatting parity means the two
languages can drift in ways that are individually fine and collectively
confusing — a Go service logging `30s` and a Python one logging `PT30S` for
the same setting. Nothing breaks, but a human reading both is worse off. The
answer is `docs/logging.md` and `docs/config.md` continuing to specify field
*semantics*, and reviewers caring about it; it is explicitly not something
this ADR mechanises.
