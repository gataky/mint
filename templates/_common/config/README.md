# config/

Checked-in configuration for this service. The keys are identical in both of
Mint's languages — that is a parity check, not a coincidence — which is why
this directory is minted from Mint's `templates/_common/` and shared by both.

| file | committed? | what it is |
| --- | --- | --- |
| `config.yaml` | yes | Defaults. The lowest-precedence source, and the documentation of every key that exists. |
| `config.local.yaml.example` | yes | A copy-me template for local overrides. |
| `config.local.yaml` | **no**, gitignored | Your machine's overrides. |

Precedence is environment variables over YAML, and there is deliberately no
third source. `make config` prints the effective configuration and names the
source that won for every key — reach for it before guessing. See
[`../docs/config.md`](../docs/config.md).

Secrets do not belong in any of these files, including the gitignored one.
They are environment variables, and a field marked secret in the config type
is masked wherever configuration is rendered.
