# Testing conventions

> **Source of truth** for how tests are laid out and named in this service.
> The tests Mint ships *are* the pattern every later test copies, so they
> carry as much weight as the application code.
>
> **Status: stub.** Filled in by Mint chunk 07. `make test` fails loudly until
> then rather than passing vacuously.

## Layout

_Mint chunk 07. Beside the code in Go; in `tests/`, mirroring the package
tree, in Python._

## Naming

_Mint chunk 07. Equivalent cases carry identical test names in both
languages, so Mint's `make parity` can diff them._

## The fake repository pattern

_Mint chunk 07._

## Integration tests

_Mint chunk 07. Excluded from `make test`, run by `make test-integration`._

## Coverage

_Mint chunk 07. Reported by `make test` in the same format in both
languages. No hard gate — a threshold on generated stub code creates busywork
rather than confidence._
