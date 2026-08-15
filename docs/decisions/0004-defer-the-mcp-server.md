# 0004 — Defer the MCP server to a later phase

**Status:** accepted (2026-08-14)
**Date:** 2026-08-14
**Chunk:** [01 — Decisions and ADRs](../../tasks/01-decisions.md)

## Context

The spec's goal statement says a running service should be "self-describing
enough that an agent can learn its capabilities without a human walking it
through them." An MCP server is the most direct expression of that, and the
operation registry already carries exactly the fields an MCP tool needs
(name, summary, input type, output type, handler). It is a fair question why
Phase 1 stops at `/openapi.json` and `/llms.txt`.

Two things forced the deferral, and one of them is dated.

**1. The protocol is still moving, and it moved seventeen days ago.**
MCP published a new specification revision on **2026-07-28**. It is not a
point release. It removed protocol-level sessions and the `Mcp-Session-Id`
header, removed the `initialize`/`notifications/initialized` handshake
entirely, removed `ping` and `logging/setLevel`, removed SSE stream
resumability, replaced server-initiated requests with a Multi Round-Trip
Requests pattern, added a mandatory `server/discover` RPC and a required
`resultType` field on every result, and deprecated the Roots, Sampling, and
Logging features outright. That is the third revision in roughly nine months
(2025-06-18 → 2025-11-25 → 2026-07-28).

The two SDKs absorbed it very differently, and the difference is the whole
argument:

| SDK | latest as of 2026-08-14 | how it absorbed 2026-07-28 |
| --- | --- | --- |
| `github.com/modelcontextprotocol/go-sdk` | **v1.7.0** (2026-07-28) | Additively. API frozen since v1.0.0 (2025-09-30); stateless mode is an opt-in field, `StreamableHTTPOptions.Stateless = true`. |
| `mcp` (Python) | **v2.0.0** (2026-07-28) | Major rework. `FastMCP` renamed to `MCPServer`; low-level `Server` handlers moved from decorators to constructor parameters; snake_case field renames; stricter validation. v1.x (v1.29.0) is maintenance-only, security fixes only. |

Had Mint shipped an MCP transport in Phase 1 at any point before July, every
generated **Python** service would today be pinned to a maintenance-only
`mcp>=1.28,<2` and would be owed a `_migrations` entry for the v1→v2 rename.
That is the concrete bill the deferral avoided, and it is the strongest
evidence available that the deferral was correct rather than merely cautious.

**2. Schema generation was assumed to be the expensive part.** It is not,
and this is worth recording because it changes the shape of the future work.
MCP tool `inputSchema`/`outputSchema` are JSON Schema 2020-12. OpenAPI 3.1
schemas are also JSON Schema 2020-12. The Go SDK's inference runs through
`github.com/google/jsonschema-go`, which exposes a **non-generic**
`jsonschema.ForType(t reflect.Type, opts *ForOptions) (*Schema, error)` —
which is precisely the call a registry holding `In any` / `Out any` can make.
Whatever ADR 0001 settles for OpenAPI generation is therefore the same
machinery MCP needs, not a second one.

### The spike

Built in a scratch directory (not the repo): a transport-agnostic registry
(`internal/service`), an error taxonomy with a transport-owned mapping table
(`internal/apierror`), an HTTP transport reading the registry
(`internal/transport/http`), and then — as the test — an MCP transport added
as a sibling (`internal/transport/mcp`), against the real
`modelcontextprotocol/go-sdk v1.7.0`. One `widgets.get` operation, one
happy path, one `not_found` path. Output:

```
HTTP  GET /widgets/w1      -> 200 {"id":"w1","name":"sprocket"}
HTTP  GET /widgets/nope    -> 404 {"status":404,"title":"not_found","type":"about:blank"}
MCP   tool widgets.get      "Fetch a widget by ID."
      inputSchema {"additionalProperties":false,"properties":{"id":{"description":
      "the widget ID to fetch","type":"string"}},"required":["id"],"type":"object"}
MCP   call widgets.get map[id:w1]   -> isError=false {"id":"w1","name":"sprocket"}
MCP   call widgets.get map[id:nope] -> isError=true  not_found
```

The MCP transport is **62 lines in one new file**. Removing that file and its
wiring and rebuilding proves the direction of the dependency:

```
$ git diff --stat            # after deleting internal/transport/mcp/
 cmd/seam/main.go                 | 38 ------------------------
 internal/transport/mcp/server.go | 62 ----------------------------------------
 2 files changed, 100 deletions(-)
$ go build ./...             # HTTP-only build
(clean)
```

Zero edits to `internal/service/`, `internal/apierror/`, or
`internal/transport/http/`. The registry seam is real.

## Decision

**No MCP server in Phase 1.** Instead, Phase 1 preserves these five
invariants, each of which must survive every chunk:

1. `internal/transport/http/` is nested one level deeper than it needs to be,
   so `internal/transport/mcp/` is a peer directory rather than a refactor.
   Nothing outside `internal/transport/http/` may import `net/http` or
   FastAPI request types. (Enforced by the `make lint` boundary check and
   stated in AGENTS.md.)
2. The operation registry (`Op`) declares nothing that only an HTTP router
   could consume, and exposes a transport-agnostic invocation path — decode
   JSON into the declared input type, call the handler, return the output
   value. `Method` and `Path` are HTTP-specific *hints* carried on `Op`; a
   second transport ignores them.
3. `internal/apierror/` owns the domain category taxonomy and the
   category→transport mapping *table*. A second transport adds a column. In
   the spike the MCP column was three lines and required no edit to
   `apierror`.
4. Schema derivation runs from `reflect.Type` (Go) / the pydantic model class
   (Python), never from a hand-written schema literal, so the same call
   produces both the OpenAPI component schema and an MCP tool schema.
5. `docs/architecture.md` records the registry as the single authoring
   location for operations, in those words, so a later contributor does not
   "helpfully" add an HTTP-only field to it.

## Alternatives considered

**Build the MCP transport in Phase 1.** Lost on the dated evidence above: on
2026-07-28 the Python SDK went to v2.0.0 with a class rename and a handler-
registration rewrite. Any service minted in the preceding months would now
need a migration Mint has no mechanism to test, in a phase where Mint has no
real services to test it against. It would also have made chunk 09's parity
requirement ("the operation lists in the Go and Python specs are identical")
substantially harder, because the two SDKs' tool-registration APIs are now
shaped very differently and the normalization would have to be invented
before the OpenAPI normalization is even proven.

**Build it now, behind a copier question (`enable_mcp: bool`).** Superficially
attractive — opt-in, so nobody pays for it. Rejected for the same reason
ADR 0006 rejects a third config source: a conditional branch in a template is
worse than an absent one. It doubles the parity matrix (four generated trees,
not two), and the `false` branch is what everyone will actually use, so the
`true` branch rots undetected. It also violates the standing rule that a
chunk which adds a guarantee adds its check: an MCP transport nobody
generates has no check that fails.

**Defer without a seam — accept a refactor later.** This is the honest
baseline, and it is not absurd: the spike says the whole MCP transport is 62
lines, so a refactor of a 62-line addition is not frightening. It lost
because the expensive part is not the transport, it is the *registry*. If
Phase 1 lets an HTTP route exist that is not in the registry, every future
transport inherits an incomplete operation list, and chunk 09's
"registry-coverage" test is the only thing standing between Mint and that
outcome. The seam that matters is free; the seam that costs (see below) is
the one being deliberately not built.

**Skip the in-process transport permanently; use a generic OpenAPI→MCP
bridge pointed at `/openapi.json`.** A serious option, and the reason this
deferral is low-risk even if the seam measures worse than it did here: a
bridge needs *zero* code in the generated service, and Mint already commits
to producing a client-generator-quality OpenAPI 3.1 document (ADR 0001). It
is not chosen as the plan because a bridge runs out of process, so spans do
not join the service's trace, request IDs do not correlate, and MCP's
`ToolAnnotations` (`readOnlyHint`, `destructiveHint`) have nowhere to come
from. But it is the fallback, and it should be named in the Phase 2 planning
rather than rediscovered.

## Consequences

**What this makes easy.** Adding MCP later is an addition, and a small one.
Concretely, from the spike, adding MCP touches:

| touched | what changes | chunk whose work is revisited |
| --- | --- | --- |
| `internal/transport/mcp/` (new) | the whole transport, ~60–100 lines per language | none — new file |
| composition root (`cmd/<svc>/main.go`, `__main__.py`) | build the MCP server, add a listener, add it to the drain loop | 06 (lifecycle) |
| `internal/config/` | one section: enabled, port or stdio, tool-name prefix | 03 (additive; a new key, no new source — see ADR 0006) |
| `internal/apierror/` | one column in the mapping table | 05 (additive) |
| `copier.yml` (both) | nothing required if MCP is always-on; one question if not | 02 |
| `internal/service/`, the registry | **nothing** for plumbing — see the honest note below for policy | 07 |

**What this makes hard — and the seam is thinner than the spec implies in
exactly two places. Both are worth stating plainly.**

*The middleware chain does not cross the seam.* `docs/architecture.md`'s
chain — recovery, request-id, tracing, metrics, auth, logging, timeout — is
frozen and parity-checked in chunk 06, and every one of those middlewares
will be written as `func(http.Handler) http.Handler` in Go and as ASGI
middleware in Python. MCP over stdio has neither. An MCP transport therefore
gets *none* of the chain for free, and the options are (a) re-implement six
middlewares in MCP-shaped form, (b) hoist the chain into a transport-neutral
interface, which is a rewrite of chunk 06's central deliverable, or (c) run
MCP only over Streamable HTTP and reuse the HTTP chain, which works but
constrains the deployment. Parity check #7 compares *the* chain against *the*
document; a second transport means either a second documented chain and a
second check, or a normalization that does not exist yet. **This is real
rework, it lands in chunk 06's territory, and the spec's deferral table does
not mention it.** The 2026-07-28 revision at least points at the answer for
one of the six: it documents OpenTelemetry context propagation over `_meta`
keys (`traceparent`, `tracestate`, `baggage`), so tracing has a defined
mechanism even if the code is different.

*The registry seam holds for plumbing and leaks for policy.* Every operation
in the registry becomes an HTTP route today. Under MCP, "every operation
becomes a tool an autonomous agent may call" is a materially different
statement, and some services will want an operation routable over HTTP but
not exposed as a tool, or exposed with `destructiveHint: true`. That means
`Op` grows at least one field (an exposure set, or an annotations struct) —
an additive change, but a change to the shape chunk 07 freezes, and one that
complicates chunk 09's registry-coverage test, which currently gets to assume
"registered ⇒ appears everywhere." Anyone adding MCP should expect to revisit
that test's assertion, not just extend it.

**What we pay in Phase 1 for the seam.** Almost nothing measurable: one extra
directory level, and the discipline of not putting `http.Request` in the
registry. That is a favourable trade even if MCP is never built.

**What would reverse this.** A Phase 2 requirement for an agent to drive a
generated service in-process with trace continuity, or a second consumer that
makes the seam pay for itself. The precondition is that ADR 0001's Go
reflection produces usable JSON Schema 2020-12 — which the spike above
demonstrates it does, via the same `jsonschema.ForType` call. If ADR 0001
concludes reflection is *not* sufficient and the registry moves to annotation
scraping, revisit this ADR: the schema-sharing argument above is what makes
MCP cheap, and it does not survive that change.

**Sources:**
[MCP 2026-07-28 changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog) ·
[Beta SDKs for the 2026-07-28 spec](https://blog.modelcontextprotocol.io/posts/sdk-betas-2026-07-28/) ·
[go-sdk releases](https://github.com/modelcontextprotocol/go-sdk/releases) ·
[python-sdk releases](https://github.com/modelcontextprotocol/python-sdk/releases)
