# config/

Checked-in configuration for this service. The keys are identical in both of
Mint's languages — that is a parity check, not a coincidence — which is why
this directory is minted from Mint's `templates/_common/` and shared by both.

**Status: empty until Mint chunk 03**, which delivers the config loader. Until
then this service reads no configuration at all; the port it listens on was
baked in at generation time from the `port` answer in `.copier-answers.yml`.

What lands here in chunk 03:

| file | committed? | what it is |
| --- | --- | --- |
| `config.yaml` | yes | Defaults. The lowest-precedence source, and the documentation of every key that exists. |
| `config.local.yaml.example` | yes | A copy-me template for local overrides. |
| `config.local.yaml` | **no**, gitignored | Your machine's overrides. |

Precedence is environment variables over YAML, and there is deliberately no
third source. See [`../docs/config.md`](../docs/config.md).

Secrets do not belong in any of these files, including the gitignored one.
