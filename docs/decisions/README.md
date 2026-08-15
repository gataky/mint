# Architecture decision records

Every generated service inherits these decisions. An env var prefix or a
metric naming scheme is nearly free to choose once and expensive to change
after forty services exist — so the reasoning has to outlive the
conversation that produced it.

## When to write one

- Anything in `prompt.md` § "Things to flag back to me"
- A call the spec doesn't dictate and the next person would plausibly make
  differently
- A deliberate *non*-decision — something deferred, with the seam that keeps
  it cheap to add later (see 0004, 0005)
- A spike that contradicted an assumption the spec was built on

Not for: choices the spec already makes, or ones with an obvious default and
no tradeoff.

## How

Copy [0000-template.md](0000-template.md), take the next free number.
Supersede rather than edit — an ADR is a record of what was decided *then*,
and rewriting it destroys the only evidence of why the code looks the way it
does. Mark the old one superseded and link forward.

## Index

All Phase 1 ADRs were produced in chunk 01 from executed spikes, and all are
accepted as of 2026-08-14. **They outrank `prompt.md`** — where the spec and
an ADR disagree, the spec is stale.

| # | decision | overturned a spec assumption? |
| --- | --- | --- |
| [0001](0001-generate-openapi-from-the-operation-registry.md) | Generate OpenAPI by reflecting over the operation registry | **yes** — pure reflection validates *and lies*; registry gains `Errors`/`Status` |
| [0002](0002-environment-variable-naming.md) | Namespace env vars `MINT_`, nest with `__` | **yes** — no bare `ENV`/`LOG_FORMAT`; single `_` is non-injective |
| [0003](0003-metric-naming-and-labels.md) | Name metrics for Prometheus, service identity in `target_info` | **yes** — turnkey instrumentation unusable in both languages |
| [0004](0004-defer-the-mcp-server.md) | Defer the MCP server | seam is real but thinner than claimed |
| [0005](0005-defer-authentication-to-a-gateway.md) | Defer auth to a gateway, reserve its slot inside logging | **yes** — slot moved one position inward |
| [0006](0006-load-config-from-env-over-yaml-only.md) | Env over YAML, and nothing else | **yes** — `pydantic_settings` silently let `.env` win |
| [0007](0007-commit-the-generated-discovery-artifacts.md) | Commit the generated discovery artifacts | no |
| [0008](0008-serve-api-and-admin-on-separate-ports.md) | Separate API and admin ports | rationale replaced: lifecycle, not security |
| [0009](0009-repo-wide-semver-tags.md) | Plain repo-wide semver, not per-template tags | **yes** — per-template `copier.yml` cannot work at all |
| [0010](0010-use-structlog-for-python-logging.md) | structlog for Python, boot uvicorn through it | **yes** — `slog.NewTextHandler` emits no color |
| [0011](0011-pinned-toolchain-versions.md) | Pin exact toolchain versions | no — but two pins were already stale security releases |
