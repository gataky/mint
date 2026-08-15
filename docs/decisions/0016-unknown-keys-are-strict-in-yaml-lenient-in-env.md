# 0016 — Unknown keys are an error in YAML and ignored in the environment

**Status:** accepted (2026-08-14)
**Date:** 2026-08-14
**Chunk:** 03
**Depends on:** [0002](0002-environment-variable-naming.md),
[0006](0006-load-config-from-env-over-yaml-only.md)

## Context

Chunk 03 had to decide what happens to a configuration key the service does
not recognise. Neither `docs/config.md` nor ADRs 0002 and 0006 said, and the
two sources pulled in opposite directions, so the implementation asked rather
than picking silently.

The question is not academic. `MINT_SERVER__PROT=8080` is a typo that will
otherwise take a real outage to find, because the service starts happily on
the default port and nothing anywhere says the variable was ignored.

## Decision

**They are treated differently, and the asymmetry is the point.**

| source | unknown key | why |
| --- | --- | --- |
| `config/config.yaml`, `config/config.local.yaml` | **error**, naming the file and the key | the file belongs to this service alone. Nothing else writes to it. A key the service doesn't recognise is a typo, and there is no other explanation available. |
| environment | **ignored** | the environment is shared. `MINT_`-prefixed variables may legitimately belong to a sibling Mint service in the same pod, the same compose project, or the same shell. |

The environment case follows directly from ADR 0002's constant `MINT_`
prefix. That decision already documented its one real cost — two Mint
services sharing an environment source cannot have different ports — and
erroring on unknown `MINT_` variables would convert that inconvenience into
a hard startup failure for the *second* service, which did nothing wrong.

## Alternatives considered

**Strict in both.** Catches the `MINT_SERVER__PROT` typo, which is the whole
motivation. Rejected because it makes a shared environment unusable: with one
ConfigMap `envFrom`-ed by three Deployments, every service fails on the other
two's keys. The failure would be immediate, total, and blamed on the wrong
service. A typo that costs an outage is bad; a design that guarantees an
outage whenever two services share config is worse.

**Lenient in both.** Consistent and simple, and it is what most config
libraries do by default. Rejected because it discards the one case where
strictness is free and unambiguous. `config.yaml` has exactly one writer; a
stray key there has no innocent explanation, and silently ignoring it is how
a service runs for a month on a default nobody intended.

**Warn rather than error on unknown YAML keys.** Tempting middle ground.
Rejected because a startup warning in a service that then works correctly is
read exactly once, by nobody. If the key is a typo the service is
misconfigured, and the spec's second principle applies: prefer the check that
fails loudly over the design that appears to work.

**Strict on `MINT_` variables, lenient on everything else.** The most
appealing rejected option, since it narrows the blast radius to Mint's own
namespace. It still breaks the shared-ConfigMap case, which is precisely the
case that uses the `MINT_` prefix, so it buys the typo-catching only in the
deployments least likely to hit the typo.

## Consequences

**A misspelled environment variable is still silent.** This is the real cost
and it should not be glossed: `MINT_SERVER__PROT=8080` starts a service on
8080's default with no complaint. The mitigations available are
`--print-config`, which shows the resolved value and its source, and the fact
that a wrong port fails loudly at the first connection attempt. Neither is a
substitute for a check, and a future phase could offer an opt-in strict mode
for single-tenant deployments.

Two developers will hit the two behaviors and reasonably expect consistency.
`docs/config.md` states both, and each error message says which file and key
it means, so the strict case explains itself at the moment it fires.
