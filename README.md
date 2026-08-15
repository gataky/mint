# Mint

Generate microservices in Go or Python from one consistent set of
[Copier](https://copier.readthedocs.io/) templates — "minting" a new service.

Run one command, answer a few prompts, get a working service. Once you're
inside a generated repo, building, running, and testing it should feel
identical regardless of which language it is: same Makefile targets, same
three-layer architecture, same log schema, same config precedence.

> **Status: Phase 1, in progress.** The templates aren't usable yet. See
> [`tasks/README.md`](tasks/README.md) for the implementation plan and what's
> done so far.

## Documentation

| | |
| --- | --- |
| **What Mint must be** | [`prompt.md`](prompt.md) — the specification |
| **How it gets built** | [`tasks/README.md`](tasks/README.md) — ordered chunks |
| **Why it's built that way** | [`docs/decisions/`](docs/decisions/README.md) — ADRs |
| **Working on this repo** | [`AGENTS.md`](AGENTS.md) |

Shared source-of-truth docs, inherited by every generated service:
[architecture](docs/architecture.md) · [logging](docs/logging.md) ·
[config](docs/config.md) · [testing](docs/testing.md) ·
[agents](docs/agents.md)

## Developer machine setup

_Filled in by chunk 10 — this is the one place asdf, direnv, and copier
installation is documented, so generated services can link here instead of
repeating it._

## Generating a service

_Chunk 10._

## Updating an existing service

_Chunk 10 — `copier update` is the whole reason Mint uses Copier rather than
cookiecutter, and it gets documented from an observed run, not from the
Copier docs._

## Changing a template

_Chunk 10 — including the rule that a copier question added to one language
must be added to both, and the versioning/tagging policy._

## Roadmap

**Phase 1** (current): app code, config, logging, errors, HTTP transport,
health, lifecycle, tracing, metrics, generated discovery docs, tests,
Makefile, asdf, direnv.

**Phase 2**: Dockerfiles, docker-compose, CI pipelines.

**Phase 3**: Kubernetes manifests.

Deferred with seams left in place: MCP servers, authentication. See the
deferral table in [`prompt.md`](prompt.md) § Scope.
