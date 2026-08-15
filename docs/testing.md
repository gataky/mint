# Testing conventions

> **Source of truth** for how tests are laid out and named in a generated
> service. The tests that ship in the template *are* the pattern every future
> service copies, so they carry as much weight as the application code.
>
> **Status: stub.** Filled in by chunk
> [07](../tasks/07-registry-and-widgets.md).

## Layout

_Chunk 07. `*_test.go` beside the code in Go; `tests/` mirroring the package
tree in Python._

## Naming

_Chunk 07. Table-driven in Go, parametrized in Python, with identical test
names for equivalent cases so `make parity` can diff them._

## The fake repository pattern

_Chunk 07._

## Integration tests

_Chunk 07. Tagged `//go:build integration` / `@pytest.mark.integration`,
excluded from `make test`, run by `make test-integration`._

## Coverage

_Chunk 07. Reported by `make test` in both languages in the same format. No
hard gate in Phase 1 — a threshold on generated stub code creates busywork
rather than confidence._
