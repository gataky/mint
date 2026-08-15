# 07 — Operation registry + widgets example

**Spec:** § Architecture rules, § The operation registry, § Testing
**Depends on:** 06; **ADR 0001 is binding here** — it changes the registry
shape the spec sketches, and it did so because the spec's version was built
and produced a document that validates and lies. ADR 0004's five invariants
also constrain this chunk.
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

1. **The registry, in ADR 0001's shape — which is not the spec's.** Each
   entry: name, summary, HTTP method, path, input type, output type,
   **`Errors`**, optional **`Status`**, handler.

   ```go
   ops.Register(ops.Op{
       Name:    "widgets.get",
       Summary: "Fetch a widget by ID.",
       Method:  http.MethodGet, Path: "/widgets/{id}",
       In:      GetWidgetInput{}, Out: Widget{},
       Errors:  []ops.Category{ops.CatNotFound, ops.CatInvalid}, // NEW
       Handler: svc.GetWidget,
       // Status int — optional; defaults to 200, or 201 for POST      // NEW
   })
   ```

   **Without `Errors`, every operation advertises an identical error set and
   `widgets.get` cannot declare its 404.** The categories come from chunk
   05's taxonomy.

   Go uses explicit registration; Python uses a decorator over the same
   shape, reading input and output types from the signature and the summary
   from the docstring, so it restates less than Go does. The two must carry
   the same information — if one can express something the other can't, cut
   it.

2. **The input and output types carry four things reflection cannot infer.**
   This is the load-bearing finding of ADR 0001: with these disabled, the
   generator produced a document that `openapi-spec-validator` reported as
   `OK` while rendering `time.Time` as `{"type":"object","properties":{}}`
   and dropping every enum. A spec that validates and lies is the worst
   available outcome, and it is what naive reflection produces **by default**.

   | what reflection cannot infer | how the type supplies it |
   | --- | --- |
   | path vs query vs header vs body | `path:` / `query:` / `header:` / `json:` struct tags — **every** input field carries exactly one |
   | the members of a named enum type | an `EnumValues() []any` method (`ops.Enumer`) — Go reflection cannot enumerate a named type's constants |
   | min / max / pattern / format | `validate:` tags, go-playground syntax |
   | `time.Time` and friends | a special-case table in the generator |

   Field *descriptions* are the fifth thing and cannot be carried at all —
   Go has no runtime access to doc comments. Chunk 09 builds the build-time
   `go/ast` pass that harvests them; don't build it here, but write the doc
   comments as you go, because they are what it harvests.

   Python carries the same information via `Annotated[...]` with
   `ops.PathParam` and pydantic `Field(...)`.

3. **Required vs optional**: `pointer OR json ",omitempty" ⇒ optional`,
   overridable with `openapi:"required"` / `openapi:"optional"`. Go cannot
   distinguish absent from zero without a pointer, so a `PATCH` body field
   that must accept an explicit zero has to be a pointer. That is a rule for
   `docs/architecture.md`, not a thing to solve. Python's
   `model_dump(exclude_unset=True)` gets this natively.

4. **Validation reads the same `validate:` tags** — `go-playground/validator`
   v10.28.0, which reports every violation at once, matching pydantic and the
   spec's multi-error requirement. Two divergences ADR 0001 measured, both of
   which must be closed here:

   - **Optional fields.** OpenAPI treats a nil pointer as absent;
     go-playground applies the constraint to the zero value anyway unless the
     tag *begins with* `omitempty`. Forgetting that prefix means the runtime
     rejects an input the published schema calls valid. This is the single
     most likely authoring mistake and is only acceptable because it is
     caught mechanically — see item 6.
   - **Enums.** `EnumValues()` feeds OpenAPI; go-playground never sees it, so
     a value the spec says cannot exist passes validation. `ops.Validate` is
     go-playground **plus an Enumer pass**.

5. **The router reads the registry, and sorts routes by specificity.** Routes
   are not registered by hand anywhere. Adding an operation is a single edit;
   there must be no way to add an HTTP route that bypasses the registry.

   **The two languages disagree about match order and the registry must
   settle it**: Go's `ServeMux` (1.22+) picks the most specific pattern
   regardless of registration order, while Starlette matches in registration
   order — so in the ADR 0001 spike `/widgets/{id}` swallowed
   `/widgets/search` and returned `{"detail": "No widget with ID search."}`.
   Identical registry content, different routing. **The registry sorts routes
   by specificity itself**, in both languages, so neither framework's default
   is load-bearing.

6. **Three generation-time checks, each exiting non-zero.** Two of them belong
   to this chunk (the third, schema validation of the emitted document, is
   chunk 09's):

   - **Structural**, all four cases proven in the spike: the path template
     and the `path:` tags agree in both directions; every input field has a
     placement tag; GET/DELETE/HEAD carry no `json:`-tagged input fields;
     operation names are unique (duplicate registration panics).
   - **`CheckOptionalConstraints`**: an optional field whose `validate` tag
     does not begin with `omitempty` is an error, because the published
     schema and the runtime check would disagree.

   Run them as tests here and wire them into `make agents-docs` in chunk 09.

7. **Python needs framework glue — budget for it.** ADR 0001 measured ~150
   lines that a normal FastAPI service would not have, and it depends on
   FastAPI internals, so a FastAPI major version can break it. Three pieces:

   - **Signature synthesis (~60 lines, `_make_endpoint`).** FastAPI derives
     path/query/body from the *endpoint function's signature*, so a handler
     declared `async def get_widget(self, inp: GetWidgetInput) -> Widget`
     makes FastAPI treat the whole model as a request body and leave `{id}`
     unbound. The registry synthesises a signature FastAPI can introspect.
     This is what buys Python **one** authoring location instead of two.
   - **`RequestValidationError` remapped to 400 problem+json**, and `422`
     stripped from the generated spec (chunk 09 does the stripping). Pydantic
     rejects a malformed body before the handler runs and returns FastAPI's
     own `{"detail": [...]}` in `application/json`; Go returns 400
     problem+json. Chunk 05 built the serializer for this.
   - **`registry.bind(svc)` at the composition root.** The decorator runs at
     class-definition time, when no instance exists, so the Python registry
     holds unbound functions. Go binds at registration because it registers
     `svc.GetWidget` directly. **This asymmetry is inherent — document it in
     `docs/architecture.md` rather than engineering it away.**

8. **The widgets resource**, threaded through all three layers:
   - `widgets.list` — `GET /widgets`
   - `widgets.get` — `GET /widgets/{id}`
   - `widgets.create` — `POST /widgets`

   Enough surface to demonstrate path params, a request body, validation, and
   at least two error categories (`not_found`, `invalid`) — and no more. This
   is a pattern to copy, not a feature.

   **The widget types must exercise the three cases that fail silently**, even
   though the operation list stays at three: one named enum type with
   `EnumValues()` (a `Status`), one optional pointer field with
   `validate:"omitempty,…"`, and one `time.Time` field. Query and header
   placement, and a `PATCH` carrying a path parameter and a body in one input
   struct, are covered by **generator tests over test-only types** — don't
   add operations to the shipped example to reach them.

9. **Layer boundaries, enforced not just described:**
   - Transport parses and serializes. No business logic, no repository
     calls.
   - Service holds all business logic and validation, takes and returns
     plain language-native types, depends on a repository *interface* it
     owns.
   - Repository implements that interface. An in-memory implementation is
     the only one in Phase 1.

   Add a lint check that fails if the service layer imports `net/http` or
   FastAPI request types, the same way chunk 03 checks env var reads. Per ADR
   0004 invariant 1 the rule is broader than the service layer: **nothing
   outside `internal/transport/http/` may import them.**

   ADR 0004's other invariants that this chunk must not break: `Op` declares
   nothing only an HTTP router could consume (`Method` and `Path` are
   HTTP-specific *hints* a second transport ignores), and schema derivation
   runs from `reflect.Type` / the pydantic model class, never from a
   hand-written schema literal.

10. **The fake in-memory repository** is the shipped example implementation
    and what service tests run against. This is the payoff of the interface
    rule — demonstrate it rather than describing it.

11. **Tests** per spec § Testing:
    - Service layer: business logic and every error category, against the
      fake repo, no I/O.
    - Transport layer: routing, binding, status codes, `problem+json` bodies.
    - Registry coverage: every registered operation is routable. (The
      OpenAPI/`llms.txt` half of this test lands in chunk 09.)
    - Route specificity: a fixture registry with a static and a parameterized
      sibling (`/things/search` and `/things/{id}`) resolves to the static
      one in **both** languages, regardless of registration order.
    - Generator/validation tests over test-only types: the four structural
      rejections, the optional-constraint check, the enum rejection, query
      and header placement, and a path-parameter-plus-body input struct.
    - Table-driven in Go, parametrized in Python, with **identical test names
      for equivalent cases** so parity can diff them.

12. **`docs/architecture.md`** — write the three-layer section and the
    registry section: what each layer may and may not import, how to add an
    operation, where the widgets example demonstrates each rule, and — this
    one matters, because the tags are undeniably dense and every future
    service inherits that density — **teach the struct tags properly**:
    placement, `validate:` with the `omitempty` prefix rule, `EnumValues()`,
    and the pointer-for-optional rule. Also record the Go/Python binding
    asymmetry from item 7, and state that the registry is *the* single
    authoring location for operations, in those words, so a later contributor
    does not "helpfully" add an HTTP-only field to it (ADR 0004 invariant 5).

13. **`docs/testing.md`** — the shared testing conventions: layout, naming,
    the fake-repository pattern, integration test tagging (`//go:build
    integration`, `@pytest.mark.integration`) and `make test-integration`.

## Out of scope

`/openapi.json` and `/llms.txt` generation, and the `go/ast` doc-comment
harvester (chunk 09) — but design the registry so they're a straightforward
read, and say in your handoff whether you believe they will be. Real
tracing/metrics (chunk 08). Any persistence beyond in-memory.

## Deliverables

- Registry in both templates, consumed by the router, with specificity
  ordering
- Widgets across all three layers, in both templates
- In-memory repository + interface
- Structural and optional-constraint checks, as tests
- Python's signature-synthesis glue and `RequestValidationError` handler
- Tests for all three layers, with matching names across languages
- Three-layer and registry sections of `docs/architecture.md`
- `docs/testing.md`
- Layer-boundary lint check wired into `make lint`

## Acceptance criteria

- All three widgets endpoints work in both generated services, with
  identical request/response bodies and status codes for identical input.
- `GET /widgets/does-not-exist` returns the `not_found` `problem+json`, byte
  identical across languages except `instance`/`trace_id`.
- `POST /widgets` with an invalid body returns the `invalid` `problem+json`
  **with status 400 and content type `application/problem+json` in both
  languages** — Python must not leak FastAPI's 422 `{"detail": [...]}`.
- Multiple violations in one request body produce multiple errors in one
  response, in both languages.
- A value outside a named enum's `EnumValues()` is rejected at runtime, not
  just absent from the spec.
- An optional field whose `validate` tag lacks the `omitempty` prefix fails
  `CheckOptionalConstraints`. Introduce one, show the failure, revert.
- Each of the four structural mistakes is rejected at generation time with a
  message naming the field and the path.
- Route specificity: `/things/search` resolves to the static route in both
  languages even when registered after `/things/{id}`.
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
  ADR 0001 settled the shape against a five-operation spike including the
  hard cases; if it turned out awkward in either language once real
  operations went through it, say so plainly and propose the revision — that
  is far cheaper now than after chunk 09 reads it.
- Any *new* drift between Python's decorator form and Go's explicit form.
  The binding asymmetry (Python binds at startup, Go at registration) is
  known, accepted, and documented — don't re-flag it. Anything else is worth
  raising.
- How big the Python glue actually came out. ADR 0001 budgeted ~150 lines
  against FastAPI internals; materially more than that, or a dependence on
  something more fragile than `_make_endpoint` / `RequestValidationError` /
  `app.openapi`, is worth knowing before chunk 09 builds on it.
- Any place the three-layer rule felt like ceremony rather than structure on
  a resource this small; the example needs to teach the pattern without
  making it look like overhead.

*Settled, do not re-open:* the `Errors` field, placement tags,
`EnumValues()`, `validate:` tags, the `time.Time` special case, and
registry-owned specificity ordering. ADR 0001, approved — and each one exists
because its absence was measured, not assumed.
