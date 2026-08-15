# 0001 — Generate OpenAPI by reflecting over the operation registry

**Status:** accepted (2026-08-14)
**Date:** 2026-08-14
**Chunk:** [01-decisions](../../tasks/01-decisions.md) (binding on 07 and 09)

## Context

The spec assumes Go can reflect over the operation registry and produce an
OpenAPI 3.1 document good enough to hand to a client generator. The registry
is upstream of routing, `/openapi.json` and `/llms.txt`, so if that assumption
is wrong, three later chunks get rewritten. This ADR settles it with a spike,
not an argument.

### What was built

A throwaway Go module (`spike`, Go 1.26.5) containing a registry, five
widgets operations, a stdlib-only reflector, a registry-driven router, and a
matching Python/FastAPI implementation. The operations were chosen to hit the
hard cases:

| operation | exercises |
| --- | --- |
| `widgets.list` `GET /widgets` | no input at all; slice response |
| `widgets.get` `GET /widgets/{id}` | path parameter; 404 |
| `widgets.create` `POST /widgets` | body, required + optional, constraints, enum, nested struct |
| `widgets.search` `GET /widgets/search` | query parameters including an enum-valued one |
| `widgets.update` `PATCH /widgets/{id}` | **path parameter and body in one input struct** |

The response types include `time.Time`, `*time.Time`, `[]string`,
`map[string]string`, `map[string]any`, a nested struct, and a self-referential
`*Widget`.

### Result 1 — pure reflection is not sufficient, and fails silently

Generating with every special case disabled produced a document that **passes
validation while being wrong**. Two examples from `openapi-naive.json`:

```json
"created_at": { "$ref": "#/components/schemas/Time" },
"status":     { "type": "string" }
```

```json
"Time": { "type": "object", "properties": {} }
```

`time.Time` has only unexported fields, so reflection sees an empty object.
`Status` is a named string type; **Go reflection cannot enumerate the
constants of a named type**, so the enum vanishes. Neither failure is
detectable by an OpenAPI validator — `openapi-spec-validator` reported
`openapi-naive.json: OK`. A spec that validates and lies is the worst
outcome available, and it is what naive reflection produces by default.

### Result 2 — reflection over a registry whose types carry four extra things *is* sufficient

Adding placement tags, `EnumValues()`, `validate` tags and a `time.Time`
special case fixed the structure. Descriptions remained: **Go has no runtime
access to doc comments at all.** A 60-line build-time pass over `go/ast`
(`cmd/docgen`) harvests them into `fielddocs.json`, which the generator loads.

```
$ go run ./cmd/docgen ./widgets fielddocs.json && go run ./cmd/spike
loaded 41 harvested doc comments
== diagnostics, reflection+tags only (33) ==
  - no description for Widget.ID (no `doc:` tag, no harvested doc comment)
  ... 32 more ...
== diagnostics, full pipeline (1) ==
  - field of interface type interface {}: no schema can be derived
```

33 gaps to 1. The remaining one is `map[string]any`, which is genuinely
unschemable and should be reported, not papered over.

### Result 3 — the generated document

`openapi.json`, 15,936 bytes, generated entirely from the registry. Excerpt:

```json
{
  "openapi": "3.1.0",
  "jsonSchemaDialect": "https://json-schema.org/draft/2020-12/schema",
  "info": { "title": "widgets", "version": "0.1.0" },
  "paths": {
    "/widgets/{id}": {
      "get": {
        "operationId": "widgets.get",
        "summary": "Fetch a widget by ID.",
        "tags": ["widgets"],
        "parameters": [
          {
            "name": "id",
            "in": "path",
            "required": true,
            "description": "ID is the widget identifier from the path.",
            "schema": { "type": "string", "minLength": 1, "maxLength": 64 }
          }
        ],
        "responses": {
          "200": {
            "description": "Success.",
            "content": {
              "application/json": {
                "schema": { "$ref": "#/components/schemas/Widget" }
              }
            }
          },
          "404": {
            "description": "Resource not found",
            "content": {
              "application/problem+json": {
                "schema": { "$ref": "#/components/schemas/Problem" }
              }
            }
          },
          "400": { "...": "problem+json" },
          "500": { "...": "problem+json" }
        }
      }
    }
  },
  "components": {
    "schemas": {
      "Status": {
        "type": "string",
        "description": "Status is the lifecycle state of a widget.",
        "enum": ["draft", "active", "retired"]
      },
      "Dimensions": {
        "type": "object",
        "required": ["height_mm", "width_mm"],
        "properties": {
          "width_mm": {
            "type": "number", "format": "double",
            "exclusiveMinimum": 0, "maximum": 10000,
            "description": "WidthMM is the widget's width in millimetres."
          },
          "depth_mm": {
            "type": "number", "format": "double", "exclusiveMinimum": 0,
            "description": "DepthMM is optional; a flat widget has no depth."
          }
        }
      },
      "CreateWidgetInput": {
        "type": "object",
        "required": ["dimensions", "name"],
        "properties": {
          "name": {
            "type": "string", "minLength": 1, "maxLength": 80,
            "description": "Name is required and must be 1-80 characters."
          },
          "status": {
            "allOf": [{ "$ref": "#/components/schemas/Status" }],
            "description": "Status defaults to draft when omitted."
          },
          "tags": {
            "type": "array", "items": { "type": "string" }, "maxItems": 10,
            "description": "Tags is optional and capped at 10 entries."
          },
          "idempotency_key": {
            "type": "string", "format": "uuid",
            "description": "IdempotencyKey de-duplicates retried creates."
          }
        }
      },
      "Problem": {
        "type": "object",
        "description": "RFC 9457 problem detail.",
        "required": ["type", "title", "status"],
        "properties": {
          "type":     { "type": "string", "format": "uri" },
          "title":    { "type": "string" },
          "status":   { "type": "integer", "format": "int64" },
          "detail":   { "type": "string" },
          "instance": { "type": "string", "format": "uri" },
          "trace_id": { "type": "string",
                        "description": "Extension member: the OpenTelemetry trace ID." }
        }
      }
    }
  }
}
```

Query parameters, from the same reflection pass over `SearchWidgetsInput`:

```json
{ "name": "q", "in": "query", "required": true,
  "schema": { "type": "string", "minLength": 1, "maxLength": 200 } },
{ "name": "limit", "in": "query", "required": false,
  "schema": { "type": "integer", "format": "int64", "minimum": 1, "maximum": 100 } },
{ "name": "status", "in": "query", "required": false,
  "schema": { "$ref": "#/components/schemas/Status" } }
```

### Result 4 — validator output

```
$ python -m openapi_spec_validator openapi.json
openapi.json: OK

$ npx @redocly/cli@2.46.1 lint openapi.json
  273:7   error    security-defined        Every operation should have security defined on it or on the root level.
  ... 4 more identical ...
  264:3   warning  info-license            Info object should contain `license` field.
  589:14  warning  no-server-example.com   Server `url` should not point to example.com or localhost.
  275:9   warning  operation-4xx-response  Operation must have at least one `4XX` response.
❌ Validation failed with 5 errors and 3 warnings.
```

No structural violations. Every Redocly "error" is its opinionated default
ruleset: `security-defined` is a direct consequence of auth being deferred
(ADR 0005), and the warnings are `license`, a localhost server URL, and
`widgets.list` legitimately having no 4xx. **`make agents-docs` should run a
schema validator, not Redocly's recommended ruleset**, or it will fail on
day one for reasons the spec deliberately chose.

### Result 5 — client generation, including a real failure

`oapi-codegen` v2.5.0 **cannot read OpenAPI 3.1 at all**:

```
$ oapi-codegen -config cfg31.yaml openapi.json
error loading swagger spec in openapi.json
: failed to load OpenAPI specification: failed to unmarshal data: json error:
  json: cannot unmarshal number into field Schema.exclusiveMinimum of type bool
```

3.1 made `exclusiveMinimum` a number; `kin-openapi`, which oapi-codegen sits
on, still models it as the 3.0 boolean. **This is not a defect in reflection.**
FastAPI's own 3.1 output fails identically:

```
$ oapi-codegen ... py/openapi-python.json
: failed to unmarshal data: json error:
  json: cannot unmarshal number into field Schema.exclusiveMinimum of type bool
```

Against a mechanically downgraded 3.0.3 copy of the same document,
oapi-codegen produced 32 KB of client code that compiles:

```go
type Widget struct {
    CreatedAt  time.Time          `json:"created_at"`
    Dimensions Dimensions         `json:"dimensions"`
    Id         string             `json:"id"`
    Labels     *map[string]string `json:"labels,omitempty"`
    Name       string             `json:"name"`
    Notes      *string            `json:"notes,omitempty"`
    Parent     *Widget            `json:"parent,omitempty"`
    Status     Status             `json:"status"`
    Tags       []string           `json:"tags"`
    UpdatedAt  *time.Time         `json:"updated_at,omitempty"`
}

const (
    Active  Status = "active"
    Draft   Status = "draft"
    Retired Status = "retired"
)

type WidgetsGetResponse struct {
    JSON200                   *Widget
    ApplicationproblemJSON400 *Problem
    ApplicationproblemJSON404 *Problem
    ApplicationproblemJSON500 *Problem
}
```

`format: date-time` became `time.Time`; the `uuid4` validate rule became
`openapi_types.UUID`; the self-reference resolved; required vs optional
became value vs pointer; each `problem+json` response is separately typed.

`openapi-typescript` 7.13.0 consumed the **native 3.1** document without
complaint and emitted `Status: "draft" | "active" | "retired"`.

One defect found and fixed during the spike: emitting the enum inline made
oapi-codegen mint four distinct Go types for one domain enum
(`WidgetStatus`, `CreateWidgetInputStatus`, `UpdateWidgetInputStatus`,
`WidgetsSearchParamsStatus`). **Named types must be published as their own
components.** After the fix: one `Status` type, three constants.

### Result 6 — the strongest evidence: a round trip

A server built from the registry, called by a client generated from that
registry's reflected document:

```
$ go test ./... -run TestRoundTrip -v
    created: id=w1 status=active created_at=2026-08-14T12:00:00Z depth=3.5
    get w1 -> 200
    404 problem+json: type=https://errors.example.com/not_found title=Resource not found
                      status=404 detail=No widget with ID nope. trace_id=000...001
    search q=sprock status=active -> total=1
    update w1 -> name="sprocket mk2" updated_at=2026-08-14T13:00:00Z
    list -> 1 widget(s)
    invalid create -> 400 name must not be empty.
--- PASS: TestRoundTrip (0.00s)
```

The same reflection produces the spec *and* the request binding, so they
cannot disagree about where a parameter lives.

### Result 7 — the mistakes are caught at generation time

```
$ go test ./ops/ -v
--- PASS: TestGenerationRejectsStructuralMistakes
    rejected with: field WidgetID tagged path:"widget_id" but "/w/{id}" has no {widget_id}
    rejected with: path "/w/{id}" declares {id} with no matching `path:` tagged field on In
    rejected with: field Name has no path/query/header/json tag; cannot place it in the request
    rejected with: GET /w/{id} has json-tagged input fields; GET must not carry a body
--- PASS: TestDuplicateOperationNamePanics
```

### Result 8 — validation constraints are a second authoring location unless forced not to be

`validate` tags feed the OpenAPI `minLength`/`maximum`/`pattern`. Do they
also feed the runtime check, or can the spec lie? `go-playground/validator`
v10.28.0 reads the same tags and reports every violation at once, matching
pydantic and the spec's multi-error requirement. But two divergences appeared:

**A. Optional fields.** OpenAPI treats a nil pointer as absent; go-playground
applies the constraint to the zero value anyway unless the tag begins with
`omitempty`. An input the published schema calls valid was rejected at
runtime:

```
buggyInput{Name: "ok"} (Notes/Tags absent):
    buggyInput.Notes: failed max=2000
```

Caught mechanically at generation time:

```
buggyInput.Notes is optional in OpenAPI but its validate tag "max=2000" does not
start with `omitempty`; the runtime check will reject an absent value the spec permits
CreateWidgetInput      clean
UpdateWidgetInput      clean
SearchWidgetsInput     clean
```

**B. Enums.** `EnumValues()` feeds OpenAPI; go-playground never sees it, so a
value the spec says cannot exist passed validation:

```
go-playground alone:
    (valid)  <-- WRONG: the spec publishes enum [draft active retired]
ops.Validate (go-playground + an Enumer pass):
    CreateWidgetInput.Status: not-a-real-status is not one of [draft active retired]
```

### Result 9 — Python: FastAPI *can* be driven from the registry, but not for free

Chunk 09 flags this as the likely failure point. It is not a failure, but the
spec's "FastAPI gives Python most of this for free" is too optimistic in one
specific way: **FastAPI derives path/query/body from the endpoint function's
signature.** A registry handler declared `async def get_widget(self, inp:
GetWidgetInput) -> Widget` makes FastAPI treat the whole model as a request
body and leave `{id}` unbound. The registry must synthesise a signature
FastAPI can introspect (~60 lines, `_make_endpoint`). With that, Python has
**one** authoring location. Three further overrides were required:

1. **Route precedence differs between the languages.** Go's `ServeMux` (1.22+)
   picks the most specific pattern regardless of registration order.
   Starlette matches in registration order, so `/widgets/{id}` swallowed
   `/widgets/search` — identical registry content, different routing:
   ```
   GET /widgets/search -> 404 {"detail": "No widget with ID search."}
   ```
   The registry now sorts routes by specificity itself.
2. **FastAPI's 422 is a wire-contract break.** Pydantic rejects a malformed
   body before the handler runs and returns `422` with FastAPI's own
   `{"detail": [...]}` in `application/json`. Go returns `400` problem+json.
   `RequestValidationError` is remapped to 400 problem+json and `422` is
   stripped from the generated spec.
3. `Problem` must be injected into `components`, because FastAPI only emits
   schemas for models it sees in a signature.

With those, the two documents agree:

```
$ python parity.py openapi.json py/openapi-python.json
go openapi:     3.1.0
python openapi: 3.1.0
operation ids identical (5): ['widgets.create', 'widgets.get', 'widgets.list',
                              'widgets.search', 'widgets.update']
  widgets.create: identical  POST   /widgets       responses=['201','400','409','500'] params=0 body=True
  widgets.get:    identical  GET    /widgets/{id}  responses=['200','400','404','500'] params=1 body=False
  widgets.list:   identical  GET    /widgets       responses=['200','500']             params=0 body=False
  widgets.search: identical  GET    /widgets/search responses=['200','400','500']      params=4 body=False
  widgets.update: identical  PATCH  /widgets/{id}  responses=['200','400','404','500'] params=1 body=True
PARITY OK
```

Python's `model_dump(exclude_unset=True)` distinguishes "absent" from
"explicitly zero" natively — the problem Go needs pointers to solve.

### Versions the spike ran against

| tool | version |
| --- | --- |
| Go | 1.26.5 |
| `go-playground/validator` | v10.28.0 |
| `oapi-codegen` | v2.5.0 (kin-openapi v0.132.0) |
| CPython | 3.14.6 |
| uv | 0.12.5 |
| FastAPI | 0.141.1 |
| pydantic | 2.13.4 |
| `openapi-spec-validator` | 0.9.0 |
| `@redocly/cli` | 2.46.1 |
| `openapi-typescript` | 7.13.0 |

These are what was *verified*, not the project's pin table.

## Decision

**Generate `/openapi.json` by reflecting over the operation registry at
runtime, supplemented by one build-time `go/ast` pass that harvests field doc
comments.** Not pure reflection, not AST codegen for the whole document, not a
hand-maintained spec.

Reflection carries structure — paths, parameters, schemas, required sets,
responses. It cannot carry intent. Four kinds of intent must be declared on
the types, and one is harvested from source:

| what reflection cannot infer | how the registry supplies it |
| --- | --- |
| path vs query vs header vs body | `path:` / `query:` / `header:` / `json:` struct tags |
| the members of a named enum type | an `EnumValues() []any` method (`ops.Enumer`) |
| min / max / pattern / format | `validate:` tags, go-playground syntax |
| `time.Time` and friends | a special-case table in the generator |
| field descriptions | `make agents-docs` runs a `go/ast` pass before generating |

**The registry entry shape changes from what the spec sketches.** It gains
`Errors` and `Status`; without `Errors`, every operation advertises an
identical error set and `widgets.get` cannot declare its 404.

```go
// internal/service/registry.go
ops.Register(ops.Op{
    Name:    "widgets.get",
    Summary: "Fetch a widget by ID.",
    Method:  http.MethodGet, Path: "/widgets/{id}",
    In:      GetWidgetInput{}, Out: Widget{},
    Errors:  []ops.Category{ops.CatNotFound, ops.CatInvalid}, // NEW
    Handler: svc.GetWidget,
    // Status int — optional; defaults to 200, or 201 for POST      // NEW
})

type GetWidgetInput struct {
    // ID is the widget identifier.        <- becomes the description
    ID string `path:"id" validate:"min=1,max=64"`
}

type CreateWidgetInput struct {
    // Name is the human-facing label.
    Name string `json:"name" validate:"min=1,max=80"`
    // Notes is optional free text.
    Notes *string `json:"notes,omitempty" validate:"omitempty,max=2000"`
    // Status defaults to draft when omitted.
    Status Status `json:"status,omitempty"`
}

type Status string
func (Status) EnumValues() []any {
    return []any{StatusDraft, StatusActive, StatusRetired}
}
```

Python carries the same information; the decorator reads input and output
types from the signature and the summary from the docstring, so it restates
less than Go does.

```python
# src/<pkg>/internal/service/widgets.py
class Service:
    @registry.register(
        name="widgets.get", method="GET", path="/widgets/{id}",
        errors=(ops.Category.NOT_FOUND, ops.Category.INVALID),
    )
    async def get_widget(self, inp: GetWidgetInput) -> Widget:
        """Fetch a widget by ID."""          # -> OpenAPI summary
        ...

class GetWidgetInput(BaseModel):
    id: Annotated[str, ops.PathParam,
                  Field(min_length=1, max_length=64,
                        description="The widget identifier.")]
```

The decorator runs at class-definition time, when no instance exists, so the
registry holds unbound functions and the composition root calls
`registry.bind(svc)` at startup. Go binds at registration because it
registers `svc.GetWidget` directly. This asymmetry is inherent and should be
documented rather than engineered away.

**Required vs optional** is `pointer OR json ",omitempty" ⇒ optional`,
overridable with `openapi:"required"` / `openapi:"optional"`. Go cannot
distinguish absent from zero without a pointer; a `PATCH` body field that
must accept an explicit zero has to be a pointer, and that is a rule for
`docs/architecture.md`, not a thing to solve.

**Three checks run in `make agents-docs` and in a test**, each exiting
non-zero:

1. Structural: path template and `path:` tags agree; every input field has a
   placement tag; no body on GET/DELETE/HEAD; operation names unique.
2. `CheckOptionalConstraints`: an optional field whose `validate` tag does not
   begin with `omitempty` is an error, because the published schema and the
   runtime check would disagree.
3. Schema validation of the emitted document — a JSON-Schema validator, not
   Redocly's recommended ruleset.

**Emit OpenAPI 3.1 as canonical and a mechanically downgraded 3.0.3 copy
alongside it**, until `kin-openapi` supports 3.1. The downgrade is ~20 lines
and only has to rewrite `exclusiveMinimum`/`exclusiveMaximum` and drop
`jsonSchemaDialect`. Serve 3.1 at `/openapi.json`.

**Publish named types as components**, never inline — verified necessary.
Attach descriptions to `$ref`s via `allOf`, so the same document downgrades
to 3.0 cleanly.

**Python** is driven from the registry, with signature synthesis,
specificity-ordered route registration, and `RequestValidationError` remapped
to 400 problem+json.

## Alternatives considered

**Pure runtime reflection, no tags, no build step.** This is what the spec
assumes and it is the one option the spike disproves outright. It produced a
document that passed `openapi-spec-validator` while representing `time.Time`
as `{"type":"object","properties":{}}` and dropping every enum. Silent
correctness failure, not a rough edge.

**Full `go/ast` codegen — scrape a package and emit the spec at build time.**
Genuinely more capable: it can read doc comments, resolve constants of a
named type without an `EnumValues()` method, and see fields reflection hides.
Rejected because it is a second authoring location by construction — the AST
tool reads *source text*, so nothing forces the generated spec to match the
registry the router actually consumed at runtime. The registry-reflection
approach makes the router and the spec read the same data structure, which is
the property the spec's principle 1 is asking for. The spike keeps `go/ast`
for the one job reflection provably cannot do (doc comments), where being a
build step is harmless because the output is descriptive, not structural.

**Annotation comments scraped by swaggo or similar.** Same second-authoring-
location objection, plus an extra toolchain, plus annotations drift from the
code beneath them exactly the way the spec says stale Swagger comments do.

**Hand-maintained `openapi.yaml`.** Drifts on the first PR. It is also
strictly worse than the alternatives here because nothing mechanical can
check it against the registry without re-deriving the registry's schema
anyway.

**Spec-first: write OpenAPI, generate Go server stubs with oapi-codegen.** A
serious option, and the one most Go shops pick. Rejected on three counts: it
inverts the spec's stated design (the registry stops being the source of
truth and becomes generated output); oapi-codegen cannot currently read 3.1,
so the authoring format would be pinned to 3.0 indefinitely; and it makes
adding a second transport (MCP, per ADR 0004) require a second generator
rather than a second reader of the registry.

**`huma` or `swaggest/openapi-go`** — existing Go libraries that do
registry-style OpenAPI generation. Not adopted, because the spec pins Go to
stdlib `net/http` with no web framework, and huma in particular brings a
router abstraction and its own operation model that would *become* the
registry. Worth revisiting if the generator grows much past the spike's
size — ~520 lines for the reflector, ~170 for the registry-driven router,
~75 for the `go/ast` doc harvester, comments included.

## Consequences

**What this makes easy.** Adding an operation is one `ops.Register` call. The
router, the spec and `llms.txt` all read the same slice, so chunk 09's
"adding an operation makes it appear in all three with no other edit" is
structurally true rather than a convention. Both languages produce
operation-identical documents, so parity check #6 is a real diff. Client
generation works today for TypeScript from the native 3.1 document and for Go
from the 3.0 downgrade.

**What this makes hard, and the honest costs:**

- **Struct tags become load-bearing.** A field's tags now determine the wire
  contract, the published schema and the runtime validation. Three checks
  catch the mistakes that matter, but the tags are undeniably dense, and
  every future service inherits that density. `docs/architecture.md` has to
  teach them properly.
- **Optional fields must be pointers**, with `validate:"omitempty,..."`.
  Forgetting the `omitempty` prefix is the single most likely authoring
  mistake; it is caught mechanically, which is the only reason this is
  acceptable.
- **Descriptions depend on a build step.** If `make agents-docs` is not run,
  the served spec has structure but no field descriptions. It degrades rather
  than breaks, and the drift check (ADR 0007) catches staleness — but the
  service's own `/openapi.json` is only as good as its last build.
- **Two documents to serve or downgrade.** Until kin-openapi supports 3.1,
  anyone generating a Go client needs the 3.0 copy. This is an ecosystem
  problem, not ours, and it affects FastAPI identically — but consumers will
  hit it and the README must say so.
- **`map[string]any` cannot be described.** The generator reports it as a
  diagnostic. Services that need it get a weaker spec for that field; the
  alternative is banning it, which seems worse.
- **Python needs ~150 lines of framework glue** that a normal FastAPI service
  would not have, and that glue depends on FastAPI internals (signature
  introspection, `RequestValidationError`, `app.openapi`). A FastAPI major
  version could break it. This is the price of Python having one authoring
  location instead of two, and it is worth paying, but it is a real
  maintenance surface and chunk 09 should budget for it.

**To reverse this**, the registry stops carrying `In`/`Out` types and becomes
a thin route table, with a hand-written or spec-first `openapi.yaml` as the
source of truth. That is a rewrite of chunk 07 and 09 and it breaks the
"single edit adds an operation" property, which is why this ADR is a
checkpoint rather than an implementation detail.

**Open question for the human.** `widgets.list` declares no error categories,
so it advertises only 200 and 500, and Redocly's default ruleset flags any
operation with no 4xx. Either every operation implicitly gains a 400, or
`make agents-docs` validates against a schema rather than a lint ruleset.
This ADR assumes the latter.
