# AGENTS.md — Mint

Context for coding agents working in this repo. Read `README.md` first.

Each service has its own `AGENTS.md` with the rules specific to it. Read the one
for the service you are changing:

- [`go-service/AGENTS.md`](go-service/AGENTS.md)
- [`py-service/AGENTS.md`](py-service/AGENTS.md)

## The one rule that spans both

**A change to the API surface must land in both services in the same change.**
There is no automated check that they agree — `scripts/compare.sh` boots both
and diffs them, but nothing runs it for you.

The API surface means: route templates, methods, status codes, response body
shapes, the `problem+json` error shape, log field names, config keys and
environment variable names, and the Makefile target list.

It does **not** mean internal layout, error wording, JSON key order, module
structure, or test names. Do not "fix" a difference in those — the two services
are meant to be idiomatic in their own languages, not transliterations of each
other.

```sh
make compare   # boots both, diffs every response, checks make help and make config
```

## Commands

```sh
make test      # both services
make lint      # both services
make fmt       # both services
make compare   # the side-by-side diff
make mint DEST=../my-svc   # generate a service from the template
make verify    # generate, build, test, lint and boot the generated service
make help      # every target
```

## The templates

`go-service/` and `py-service/` are **reference services**: they stay runnable,
they are what `make compare` diffs, and they are where a new idea is worked out.
`templates/<lang>-service/template/` is the **deliverable**: a parameterized
copy of that tree that Copier renders into a new service.

A change to a reference service does not reach the template by itself. Land it
in both, in the same change, and run `make verify`.

```
copier.yml                       the single template definition, at the repo root
questions-shared.yml             the language-agnostic question set, !include-ed
templates/go-service/template/   the parameterized Go tree
scripts/verify-template.sh       generate → build → test → lint → boot → assert
```

**`copier.yml` must live at the repo root, and there is exactly one of it.**
Copier treats a path as VCS-tracked only when it *is* the git repo root; a
`copier.yml` under `templates/go-service/` records no `_commit` and makes
`copier update` fail with "cannot obtain old template references".

### Writing template source

- **The variable delimiter is `{@ @}`**, set in `_envops`. Blocks and comments
  stay on Jinja's defaults, `{% %}` and `{# #}`. `{{ }}` is unusable — Helm and
  GitHub Actions' `${{ }}` both use it — and Go's `[]Listener{{...}}` shows why
  the delimiter has to dodge the languages the templates are *written* in.
- **`_templates_suffix` is `""`, so every file is rendered.** Source files keep
  their real extensions — `main.go` is `main.go`, not `main.go.jinja`. A literal
  `{%` or `{#` in template source would need escaping; nothing in the Go, Make
  or YAML we ship uses either.
- **A file that renders to an empty name is skipped.** That is how the example
  resources are gated: `internal/domain/{% if include_examples %}widget.go{% endif %}`.
  Anything conditional at file granularity should use that rather than a
  `{% if %}` wrapped around the file's whole contents.
- **Copier picks up uncommitted template changes automatically** (it warns
  `DirtyLocalWarning`). There is no commit-to-test cycle — but a service
  generated from a dirty tree records a `_commit` that does not exist, and
  `copier update` in it later fails with `error: pathspec ... did not match`.
  Generate from a clean checkout whenever the result needs to be updatable.

### Both answers to every question have to compile

`include_examples: false` is a supported answer, not a degraded one. It removes
16 files, changes the signature of `NewAPI`, and leaves `problem()` and
`checkContext()` without callers. Three things exist only to keep that answer
first-class:

- `internal/transport/http/helpers_test.go` — the shared test helpers, so that
  removing the example resources does not take `do()` and `decode()` with them.
- `internal/transport/http/{% if not include_examples %}smoke_test.go{% endif %}` —
  the error contract, access log and OpenAPI document tested without any
  resource, so `make test` is meaningful from the first commit.
- A gated `unused` exclusion in `.golangci.yml` for the scaffolding the first
  resource will call.

Those three have no counterpart in `go-service/`. That divergence is deliberate
and is the only one; anything else that differs is drift.

`make verify` runs both answers end to end. It is the check that matters — run
it after every template change.

## Working on prompt.md

`prompt.md` is the original specification. It describes a considerably more
elaborate system than what is built — an operation registry driving codegen,
seventeen ADRs, a ten-check parity suite, generated `llms.txt`, a committed and
downgraded OpenAPI document.

Those were deliberately cut in favour of using each framework's own
capabilities. **Do not treat `prompt.md` as a to-do list.** It is worth reading
for its findings — the environment variable naming rationale, the uvicorn signal
handling trap, ruff's changing defaults — but where it and this repo disagree,
this repo is what exists.
