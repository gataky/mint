# AGENTS.md — Mint

Context for coding agents working in this repo. Read `README.md` first — it
explains the split across `github.com/dyosmos`: the Copier templates minted
from the two reference services here live in their own repos, and so do the two
outbound HTTP client libraries, `go-http-client` and `py-http-client`.

Each directory under `foundry/` has its own `AGENTS.md` with the rules specific
to it. Read the one for what you are changing:

- [`foundry/go-service/AGENTS.md`](foundry/go-service/AGENTS.md)
- [`foundry/py-service/AGENTS.md`](foundry/py-service/AGENTS.md)

The template-authoring rules (the `{@ @}` delimiter, gated files, the
`include_examples: false` requirement, `copier.yml`'s VCS-root constraint) now
live in `go-service-template`'s and `py-service-template`'s own `AGENTS.md`,
since template source no longer lives in this repo. Each client library's rules
live alongside it in its own repo.

## The one rule that spans both services

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

## A second rule, new since the split

**A change to the API surface is not done when it lands here.** `foundry/` is
the reference; the deliverable a developer actually mints from is
`go-service-template` or `py-service-template`, in the `dyosmos` org. Carry the
change into the matching template repo as a follow-up — its own `make verify`
is the check that it rendered correctly. Nothing today catches a `foundry/`
change that never made it to its template; see "Cross-repo drift detection" in
README.md.

## Commands

```sh
make test      # both services
make lint      # both services
make fmt       # both services
make compare   # the side-by-side diff
make help      # every target
```

## The reference services

`foundry/go-service/` and `foundry/py-service/` are **reference services**:
they stay runnable, and they are what `make compare` diffs. A new idea is
worked out here first, proven against both languages, and only then carried
into the template repos.

```
foundry/go-service/              the runnable Go reference service
foundry/py-service/              the runnable Python reference service
scripts/compare.sh               boots both, diffs every response, request by request
scripts/metric-families.py       parses /metrics into comparable families
```

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
