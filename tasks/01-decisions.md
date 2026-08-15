# 01 — Decisions and ADRs

**Spec:** § Things to flag back to me, § Decisions, § Scope (deferral table)
**Depends on:** 00
**Size:** M
**Standing rules:** [tasks/README.md](README.md#standing-rules--these-apply-to-every-chunk)

## Goal

Resolve every decision that later chunks would otherwise make silently and
inconsistently, and record each as an ADR. **This chunk writes no
application code.** Small throwaway spikes to answer a feasibility question
are fine and expected — put them in a temp dir, not in the repo.

The point is that chunk 07 shouldn't be discovering that Go can't reflect
its way to a usable OpenAPI spec after three layers are built on the
assumption that it can.

## Do

Research and write one ADR per item. Where the spec says "propose one,"
propose it here rather than in code.

**0001 — Go OpenAPI generation from the operation registry.** The
load-bearing one. Determine whether reflecting over registry entries in Go
produces an OpenAPI 3.1 spec good enough to feed a client generator — path
params, request/response schemas, enums, required vs optional, error
responses. Build a throwaway spike to prove it, don't reason about it in the
abstract. If reflection isn't sufficient, the alternatives are annotation
scraping via `go/ast` or a hand-maintained spec; say which, and what the
registry's shape has to become. Include the concrete proposed registry API
for both languages in this ADR.

**0002 — Environment variable naming scheme.** Propose the prefix and the
section/key convention (spec suggests `MINT_<SECTION>_<KEY>`), how nesting
maps, and how Go and Python differ only in casing. Every future service
inherits this, so it's expensive to change.

**0003 — Metric naming convention.** Propose the pattern, the standard
label set (including whether `service_owner` is a label), and write down the
cardinality rule.

**0004 — MCP deferred.** Record why (SDK churn and schema-generation
complexity before the core is proven), and — more importantly — the seam:
`internal/transport/http/` nests one level deeper than it needs to, and the
operation registry is transport-agnostic. State what adding MCP later would
actually touch.

**0005 — Auth deferred.** Record the expectation that auth lands at a
gateway or mesh, and name its reserved slot in the middleware chain. The
chain gets frozen and parity-checked in chunk 06, so the slot must exist
before then.

**0006 — Config sources: env > YAML, no third source.** Record that JSON was
considered and dropped, and where a third source would go if one is ever
justified.

**0007 — Are generated artifacts committed?** `openapi.json` and `llms.txt`:
committed so drift shows up as a PR diff, or gitignored build output.
Consequences for `make agents-docs` and for the drift check either way.

**0008 — Port strategy.** Split `port` / `admin_port` with `admin_port`
defaulting to `port + 1000`, versus a single listener. Record the
deployment assumption the choice rests on.

**0009 — Per-template versioning.** `go-service/v1.2.0` and
`python-service/v1.2.0` moving independently: confirm this works with
`copier update` in practice (spike it), and decide what a
`templates/_common/` change bumps.

**0010 — Python logging library.** structlog vs alternatives, judged on
whether one set of call sites can render both a colorized console tier and a
JSON tier cleanly. Justify against the spec's two-tier requirement.

Also: pin and record the exact versions this project will use for Go,
CPython, uv, golangci-lint, gofumpt, ruff, and mypy. That list becomes
`.tool-versions` and the dev-dependency pins in chunk 02.

## Out of scope

Any code in `templates/`. Any `copier.yml`. Do not start chunk 02 because
the answers feel obvious.

## Deliverables

- `docs/decisions/0001-*.md` through `0010-*.md`
- A pinned-versions table in the ADR for 0001 or its own short ADR
- A short summary comment on this chunk's handoff listing each decision in
  one line, so the human can approve or override without reading ten files

## Acceptance criteria

- Every item in spec § "Things to flag back to me" maps to exactly one ADR.
- ADR 0001 references an actual spike — a real generated OpenAPI document
  produced from a real Go registry prototype, quoted or attached — not an
  argument from first principles.
- Each ADR has status, context, decision, and consequences.
- No files created under `templates/`.

## Flag back before finishing

All of it. This chunk's entire output is decisions the human needs to
approve. Present them as a list with your recommendation on each, and
explicitly call out any where the spike contradicted what the spec assumed —
especially ADR 0001, since the spec's registry design depends on its answer.
