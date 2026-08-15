# Changelog

Templates are versioned and tagged independently — `go-service/vX.Y.Z` and
`python-service/vX.Y.Z` — so a Python-only fix doesn't bump the mint mark on
every Go service. Per-template changelogs live alongside each template once
they exist; this file tracks the repo itself.

## [Unreleased]

### Added
- Repo skeleton, self-documenting Makefile, ADR template, and stubs for the
  five shared source-of-truth docs (chunk 00).
- Specification (`prompt.md`) and the ordered implementation chunks
  (`tasks/`).
