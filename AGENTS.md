# AGENTS.md — Mint

Context for coding agents working in this repo. Read `README.md` first.

Each service has its own `AGENTS.md` with the rules specific to it. Read the one
for the service you are changing:

- [`go-service/AGENTS.md`](go-service/AGENTS.md)
- [`python-service/AGENTS.md`](python-service/AGENTS.md)

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
make help      # every target
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
