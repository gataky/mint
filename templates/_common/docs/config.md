# Configuration

> **Source of truth** for this service's configuration precedence, its
> environment variable naming scheme, and its secrets stance. The README links
> here rather than restating it.
>
> **Status: stub.** Filled in by Mint chunk 03. Until then the service reads
> no configuration at all: the port it listens on was baked in at generation
> time from the `port` answer in `.copier-answers.yml`.

## Precedence

_Mint chunk 03. Environment variables beat YAML, and there is deliberately no
third source._

## Environment variable naming

_Mint chunk 03._

## Environments

_Mint chunk 03. `local | dev | staging | prod`, and nothing else._

## Validation

_Mint chunk 03. Configuration is validated at startup; an invalid value stops
the process rather than surfacing as a request-time failure._

## Secrets

_Mint chunk 03._

## Local overrides

_Mint chunk 03 makes `config/config.local.yaml` load._

Two local-override mechanisms are already wired, and both are gitignored:

- `.env` — read by direnv through `dotenv_if_exists`, so the values arrive as
  ordinary environment variables before any process starts.
- `config/config.local.yaml` — read by the config loader once chunk 03 ships.
