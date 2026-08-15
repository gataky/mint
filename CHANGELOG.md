# Changelog

Templates are versioned and tagged independently — `go-service/vX.Y.Z` and
`python-service/vX.Y.Z` — so a Python-only fix doesn't bump the mint mark on
every Go service. Per-template changelogs live alongside each template once
they exist; this file tracks the repo itself.

## [Unreleased]

### Added
- `common:` Repo skeleton, self-documenting Makefile, ADR template, and stubs
  for the five shared source-of-truth docs (chunk 00).
- `common:` Specification (`prompt.md`) and the ordered implementation chunks
  (`tasks/`).
- `common:` Eleven ADRs (`docs/decisions/0001`–`0011`), each from an executed
  spike, all accepted 2026-08-14 (chunk 01).

### Changed
- `common:` Toolchain pinned to Go 1.26.6 and CPython 3.14.7 — both security
  releases, per ADR 0011.
- `common:` The spec's repo layout, versioning scheme, registry shape, env var
  scheme, middleware order, and logging stack were all revised to match what
  the spikes found. Five spec assumptions were disproved; three of them had
  been failing silently.
