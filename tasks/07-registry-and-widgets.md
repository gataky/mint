# 07 — Operation registry + widgets example

**Spec:** § Architecture rules, § The operation registry, § Testing
**Depends on:** 06; **ADR 0001 is binding here**
**Size:** L
**Standing rules:** [tasks/README.md](README.md#standing-rules--these-apply-to-every-chunk)

> **Human checkpoint after this chunk.** The registry is upstream of routing,
> OpenAPI, and `llms.txt`. If its shape is wrong, chunks 08–09 get rewritten.

## Goal

The three-layer architecture becomes concrete: one example resource threaded
through transport, service, and repository, with every operation declared
exactly once in a registry that the router consumes — and that chunk 09 will
consume again for OpenAPI and `llms.txt`.

## Do

1. **The registry**, in the shape settled by ADR 0001. Each entry: name,
   summary, HTTP method, path, input type, output type, handler. Go uses
   explicit registration; Python uses a decorator over the same shape. The
   two must carry the same information — if one can express something the
   other can't, cut it.

2. **The router reads the registry.** Routes are not registered by hand
   anywhere. Adding an operation is a single edit; there must be no way to
   add an HTTP route that bypasses the registry. If there is, that's a
   design failure to fix, not to document around.

3. **The widgets resource**, threaded through all three layers:
   - `widgets.list` — `GET /widgets`
   - `widgets.get` — `GET /widgets/{id}`
   - `widgets.create` — `POST /widgets`

   Enough surface to demonstrate path params, a request body, validation, and
   at least two error categories (`not_found`, `invalid`) — and no more. This
   is a pattern to copy, not a feature.

4. **Layer boundaries, enforced not just described:**
   - Transport parses and serializes. No business logic, no repository
     calls.
   - Service holds all business logic and validation, takes and returns
     plain language-native types, depends on a repository *interface* it
     owns.
   - Repository implements that interface. An in-memory implementation is
     the only one in Phase 1.

   Add a lint check that fails if the service layer imports `net/http` or
   FastAPI request types, the same way chunk 03 checks env var reads.

5. **The fake in-memory repository** is the shipped example implementation
   and what service tests run against. This is the payoff of the interface
   rule — demonstrate it rather than describing it.

6. **Tests** per spec § Testing:
   - Service layer: business logic and every error category, against the
     fake repo, no I/O.
   - Transport layer: routing, binding, status codes, `problem+json` bodies.
   - Registry coverage: every registered operation is routable. (The
     OpenAPI/`llms.txt` half of this test lands in chunk 09.)
   - Table-driven in Go, parametrized in Python, with **identical test names
     for equivalent cases** so parity can diff them.

7. **`docs/architecture.md`** — write the three-layer section and the
   registry section: what each layer may and may not import, how to add an
   operation, and where the widgets example demonstrates each rule.

8. **`docs/testing.md`** — the shared testing conventions: layout, naming,
   the fake-repository pattern, integration test tagging (`//go:build
   integration`, `@pytest.mark.integration`) and `make test-integration`.

## Out of scope

`/openapi.json` and `/llms.txt` generation (chunk 09) — but design the
registry so they're a straightforward read, and say in your handoff whether
you believe they will be. Real tracing/metrics (chunk 08). Any persistence
beyond in-memory.

## Deliverables

- Registry in both templates, consumed by the router
- Widgets across all three layers, in both templates
- In-memory repository + interface
- Tests for all three layers, with matching names across languages
- Three-layer and registry sections of `docs/architecture.md`
- `docs/testing.md`
- Layer-boundary lint check wired into `make lint`

## Acceptance criteria

- All three widgets endpoints work in both generated services, with
  identical request/response bodies and status codes for identical input.
- `GET /widgets/does-not-exist` returns the `not_found` `problem+json`, byte
  identical across languages except `instance`/`trace_id`.
- `POST /widgets` with an invalid body returns the `invalid` `problem+json`.
- Service-layer tests run with no network and no filesystem.
- `make lint` fails if the service layer imports `net/http` or a FastAPI
  request type. Demonstrate, then revert.
- Registry-coverage test passes: every registered operation is routable.
- `make test` passes in both, and prints coverage in the same format.
- `scripts/parity.sh` gains a check diffing the registry operation lists and
  the test case names between the two services.
- `scripts/verify-template.sh` grows to exercise all three widgets endpoints.

## Flag back before finishing

- **Whether the registry actually held up.** This is the checkpoint chunk.
  If ADR 0001's design turned out awkward in either language once real
  operations went through it, say so plainly and propose the revision — that
  is far cheaper now than after chunk 09 reads it.
- Whether Python's decorator form and Go's explicit form drifted in what
  they can express.
- Any place the three-layer rule felt like ceremony rather than structure on
  a resource this small; the example needs to teach the pattern without
  making it look like overhead.
