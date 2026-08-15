# 0011 — Pin exact toolchain versions for Go, Python and all linters

**Status:** accepted (2026-08-14)
**Date:** 2026-08-14
**Chunk:** [01 — Decisions and ADRs](../../tasks/01-decisions.md)

## Context

Spec § "Version pinning" requires that "latest stable" mean *latest stable at
template-authoring time, pinned into the template* — never resolved during
`copier copy` — so that "two developers minting a week apart must get
byte-identical toolchains, or the mint mark stops identifying a build."

Two things had to be established rather than assumed:

1. What is actually current stable, on 2026-08-14. The repo root
   `.tool-versions` already carries `golang 1.26.5`, `python 3.14.6`,
   `uv 0.12.5`.
2. Whether CPython 3.14 is a version FastAPI, pydantic and the OpenTelemetry
   Python SDK all genuinely support. 3.14 is recent; a classifier is not
   proof, and discovering the answer in chunk 02 would be expensive.

### CPython 3.14 support — resolved and executed, not read off PyPI

`uv 0.12.5` resolved the full intended Python runtime set against 3.14, then
the resolution was installed into a real CPython 3.14.6 interpreter and run:

```
$ uv pip compile --python-version 3.14 --no-header requirements.in
fastapi==0.141.1
opentelemetry-api==1.44.0
opentelemetry-exporter-otlp-proto-grpc==1.44.0
opentelemetry-instrumentation-fastapi==0.65b0
opentelemetry-sdk==1.44.0
prometheus-client==0.26.0
pydantic==2.13.4
pydantic-settings==2.15.0
starlette==1.6.0
structlog==26.1.0
uvicorn==0.52.3

$ uv pip compile --python-version 3.14 --no-header dev-requirements.in
httpx==0.28.1
mypy==2.3.0
pytest==9.1.1
pytest-asyncio==1.4.0
ruff==0.16.3
```

Resolution alone only proves metadata agreement, so the stack was exercised —
a FastAPI app with a pydantic response model, `pydantic-settings`, and
`FastAPIInstrumentor` over a real `TracerProvider`:

```
$ .venv/bin/python smoke.py
HTTP 200 {'id': 'abc', 'name': 'w'}
openapi paths: ['/widgets/{wid}']
settings: {'port': 8080}
span exported: True

$ .venv/bin/python -c "…"
CPython       3.14.6
fastapi       0.141.1
pydantic      2.13.4
otel sdk      1.44.0
structlog     26.1.0
ALL IMPORTS OK on CPython 3.14.6

$ .venv/bin/ruff --version   -> ruff 0.16.3
$ .venv/bin/mypy --version   -> mypy 2.3.0 (compiled: yes)
$ .venv/bin/pytest --version -> pytest 9.1.1
```

**No dependency blocks CPython 3.14.** Serving, OpenAPI generation, settings
loading and span export all work. Three things surfaced that chunk 02 needs:

- `opentelemetry-instrumentation-fastapi` resolves to **`0.65b0` — a beta
  version string.** That is normal for the whole OTel Python *contrib*
  line (the instrumentation packages version `0.x` in lockstep with the
  stable `1.44.0` API/SDK), but it means the pin must be exact and `uv.lock`
  must be committed; a range would happily float across beta releases.
- Starlette 1.6.0 emits, from `fastapi.testclient`:
  `StarletteDeprecationWarning: Using 'httpx' with 'starlette.testclient' is
  deprecated; install 'httpx2' instead.` The Python template's test
  dependency should be **`httpx2`**, not `httpx`, or `make test` ships a
  deprecation warning in every generated service on day one.
- **ruff 0.16.0 changed the default rule set from 59 rules to 413**, and
  dropped 18 (E401, E402, E7xx, E711-714, E721, E731, E741-743, F403,
  F405-406, F722) from defaults. The template must check in an explicit
  `[tool.ruff.lint] select`; inheriting ruff's defaults would make `make lint`
  behave differently across ruff versions, which is exactly what pinning is
  meant to prevent.

### Current stable, checked on 2026-08-14

`.tool-versions` is behind on two of three pins. Both gaps are security
releases:

- **Go 1.26.6** shipped 2026-08-13 with security fixes to the `go` command
  and `crypto/tls`, `encoding/asn1`, `encoding/xml`, `html/template`, `net`,
  `net/http`, `net/url`. The repo pins 1.26.5 (2026-07-07). Go 1.27 is at
  rc3 — not stable.
- **CPython 3.14.7** shipped 2026-08-05. The repo pins 3.14.6 (2026-06-10).
  3.14 is the current stable series; 3.15 is at rc1, scheduled 2026-10-01.
- **uv 0.12.5** (2026-08-14) is current. The existing pin is correct.

Both target versions are already installable via asdf, so the bump is not
blocked:

```
$ asdf list all golang | grep '^1\.26\.'
1.26.3  1.26.4  1.26.5  1.26.6
$ asdf list all python | grep -E '^3\.1[45]\.'
3.14.6  3.14.6t  3.14.7  3.14.7t  3.15.0rc1  3.15.0rc1t
$ asdf list all uv | tail -3
0.12.4  0.12.5
```

### How the Go linters get pinned exactly

`.tool-versions` covers languages; it should not also grow linter entries
that only asdf understands. Go 1.24+ `tool` directives pin linters in
`go.mod`, which is version-controlled with the service and honoured by
`go tool`. Verified on the pinned Go:

```
$ go get -tool mvdan.cc/gofumpt@v0.11.0
$ go get -tool github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.12.2
$ grep -E '^tool' -A3 go.mod
tool (
	github.com/golangci/golangci-lint/v2/cmd/golangci-lint
	mvdan.cc/gofumpt
$ go tool gofumpt --version
v0.11.0 (go1.26.5)
$ go tool golangci-lint --version
golangci-lint has version 2.12.2 built with go1.26.5
```

golangci-lint 2.x also requires an explicit schema version in its config —
a v1-shaped `.golangci.yml` is a hard error, not a warning:

```
$ go tool golangci-lint config verify        # .golangci.yml without a version key
The command is terminated due to an error: can't load config: unsupported
version of the configuration: "" See https://golangci-lint.run/docs/product/migration-guide

$ printf 'version: "2"\nlinters:\n  enable:\n    - govet\n' > .golangci.yml
$ go tool golangci-lint config verify        # exit 0
```

## Decision

Pin exactly these versions. No ranges, no `latest`, no `^`/`~`, anywhere.

| tool | **pin** | current stable (date) | where the pin lives | source, fetched 2026-08-14 |
| --- | --- | --- | --- | --- |
| Go | **1.26.6** | 1.26.6 (2026-08-13) | `.tool-versions`, `go 1.26.6` in `go.mod` | [go.dev/doc/devel/release](https://go.dev/doc/devel/release) |
| CPython | **3.14.7** | 3.14.7 (2026-08-05) | `.tool-versions`, `requires-python == "3.14.*"` in `pyproject.toml` | [python.org/downloads](https://www.python.org/downloads/) |
| uv | **0.12.5** | 0.12.5 (2026-08-14) | `.tool-versions` | [github.com/astral-sh/uv releases](https://github.com/astral-sh/uv/releases/latest) |
| golangci-lint | **2.12.2** | v2.12.2 (2026-05-06) | `tool` directive in `go.mod` | [github.com/golangci/golangci-lint releases](https://github.com/golangci/golangci-lint/releases/latest) |
| gofumpt | **0.11.0** | v0.11.0 (2026-07-27) | `tool` directive in `go.mod` | [github.com/mvdan/gofumpt releases](https://github.com/mvdan/gofumpt/releases/latest) |
| ruff | **0.16.3** | 0.16.3 (2026-08-13) | `[dependency-groups] dev` in `pyproject.toml` + `uv.lock` | [pypi.org/project/ruff](https://pypi.org/project/ruff/) |
| mypy | **2.3.0** | 2.3.0 (2026-07-13) | `[dependency-groups] dev` in `pyproject.toml` + `uv.lock` | [pypi.org/project/mypy](https://pypi.org/project/mypy/) |

**Change the repo root `.tool-versions`** from `golang 1.26.5` / `python
3.14.6` to:

```
golang 1.26.6
python 3.14.7
uv 0.12.5
```

Both bumps are security releases; both are asdf-installable today. The spike
above ran on 1.26.5 / 3.14.6 (what this machine has installed) — the patch
delta is security and bugfix only, no API surface, so the results carry.
Chunk 02 must `asdf install` both before generating anything.

Runtime dependency pins for the Python template, from the verified
resolution — exact, with `uv.lock` committed:

| package | pin |
| --- | --- |
| fastapi | 0.141.1 |
| pydantic | 2.13.4 |
| pydantic-settings | 2.15.0 |
| starlette | 1.6.0 (via fastapi) |
| uvicorn | 0.52.3 |
| structlog | 26.1.0 |
| prometheus-client | 0.26.0 |
| opentelemetry-api / -sdk | 1.44.0 |
| opentelemetry-exporter-otlp-proto-grpc | 1.44.0 |
| opentelemetry-instrumentation-fastapi | 0.65b0 |
| pytest / pytest-asyncio | 9.1.1 / 1.4.0 |

Three configuration consequences follow from the pins and are part of this
decision:

- `.golangci.yml` starts with `version: "2"`.
- `pyproject.toml` carries an explicit `[tool.ruff.lint] select`, never
  ruff's defaults.
- The Python test client dependency is `httpx2`, not `httpx`.

Per ADR [0009](0009-repo-wide-semver-tags.md), bumping any version in this
table is a change to the mint repo that bumps the single repo-wide semver tag
— PATCH when no interface moves — and reaches existing services through
`copier update`.

## Alternatives considered

**Leave `.tool-versions` at `golang 1.26.5` / `python 3.14.6`.** Rejected:
1.26.6 and 3.14.7 are security releases, and the whole point of pinning is
that *someone* decides when to move, deliberately. Shipping a template that
mints every future service onto a known-superseded patch release makes the
first security bump a fleet-wide `copier update` instead of a non-event.

**Pin Go 1.27 or CPython 3.15.** Rejected: both are release candidates
(go1.27rc3, 3.15.0rc1) on 2026-08-14. Spec § "Language-specific stack" says
latest *stable*, and § "Python" adds "that all listed dependencies support" —
OTel and FastAPI have not shipped 3.15 wheels.

**Pin CPython 3.13 to be conservative.** Rejected: the spike proves 3.14 works
end to end, including span export through the contrib instrumentation, which
is the piece most likely to lag. Choosing 3.13 would cost a migration later
for no measured benefit.

**Floating minor versions (`golang 1.26`, `ruff >=0.16,<0.17`).** Rejected
directly by spec § "Version pinning" — two developers minting a week apart
must get byte-identical toolchains. Ruff 0.16.0's 59 → 413 default-rule
change is the concrete illustration: a range would let `make lint` change
verdict without anything in the service changing.

**Install golangci-lint and gofumpt through asdf entries in
`.tool-versions`.** Rejected: it puts Go tooling in two pinning systems and
requires every developer to have those asdf plugins. `go tool` needs nothing
beyond the pinned Go, and the pin travels in `go.mod` where a reviewer sees
it in the diff.

**Install the Go linters with `go install …@version` in the Makefile.**
Rejected: it writes into a shared `GOBIN`, so two services on different
golangci-lint versions fight over one binary — the exact
non-reproducibility this ADR exists to remove.

## Consequences

**Easy.** Every generated service is byte-reproducible from its mint mark:
`.tool-versions` plus `go.mod` plus `uv.lock` fully determine the toolchain.
`make lint` gives the same verdict on a laptop and in Phase 2 CI without a
CI-specific install step. Bumping a version is one PR in mint, one tag, and a
`copier update` per service.

**Hard, and named honestly:**

- **`go get -tool github.com/golangci/golangci-lint/v2/…` added 212
  `// indirect` requires** to the spike's `go.mod`. Every generated Go service
  inherits a large linter dependency graph in its main module, which lengthens
  `go mod download`, enlarges `go.sum`, and puts linter dependencies in front
  of anyone auditing the service's supply chain. The escape hatch, if this
  becomes intolerable, is a separate `tools/go.mod` — at the cost of a second
  module in every service and a second thing `make lint` has to know about.
  Taken deliberately: one module is simpler, and the noise is confined to
  `go.sum`.
- **Pinning is a standing maintenance obligation.** Seven tools plus eleven
  Python packages, each of which will be stale within weeks — Go and ruff both
  released *yesterday* relative to this ADR. Without an automated bump PR in
  Phase 2, the pins rot and "latest stable at authoring time" becomes "latest
  stable in August 2026" forever.
- **`opentelemetry-instrumentation-fastapi 0.65b0` is a beta version string
  in a template that promises byte-identical toolchains.** It is the upstream
  project's normal versioning, but any tooling that filters prereleases (and
  `copier`'s own `--prereleases` flag is a reminder that some does) needs to
  be told to allow it.
- **A CPython bump is not free for Python services**, because `uv.lock`
  resolves against `requires-python`. Moving off 3.14 means re-resolving and
  re-verifying the whole set, which is why the pin is `3.14.*` and not a
  floor.

**To reverse a pin**, change it in mint, re-run the § "Version pinning"
verification above (`uv pip compile` + install + smoke), bump the repo tag,
and let `copier update` carry it. Reversing the *strategy* — floating instead
of pinning — would invalidate the mint mark as a build identifier and
contradict spec § "Version pinning"; it should be a spec change, not a code
change.
