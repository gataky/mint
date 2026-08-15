# 10 — Docs, proof, and tag

**Spec:** § Parity enforcement, § Copier mechanics (versioning, updates),
§ asdf + direnv, § Deliverables
**Depends on:** 09
**Size:** M
**Standing rules:** [tasks/README.md](README.md#standing-rules--these-apply-to-every-chunk)

## Goal

Close out Phase 1: finish the documentation, prove the harnesses actually
catch drift rather than merely passing, prove `copier update` works, and tag
the first release so the mint mark renders.

## Do

1. **Complete `scripts/parity.sh`** — all eight checks from spec § Parity
   enforcement, including any that earlier chunks stubbed. Each check should
   name what diverged and where, not just exit 1.

2. **Complete `scripts/verify-template.sh`** — generate both, build, boot,
   exercise `/healthz`, `/readyz`, `/metrics`, all three widgets endpoints,
   `/llms.txt`, `/openapi.json`; assert a log line in each tier and an
   exported span; SIGTERM and assert clean drain; tear down. Assertions, not
   eyeballing.

3. **Prove drift detection.** For each of the eight parity checks, introduce
   the drift it's meant to catch, confirm it fails, and revert. A parity
   suite that has never failed is not known to work. Record the results as a
   table in the handoff — one row per check, what was broken, what the
   failure output said.

4. **Prove `copier update`.** Generate a service from the current template,
   commit it, make a non-trivial template change (add a config key and a
   Makefile target), tag it, run `copier update` in the generated service,
   and confirm the change lands cleanly. Do this for both languages.
   Document the workflow in the README from what you actually observed, not
   from the Copier docs.

5. **Top-level `README.md`**: what Mint is; one-time machine setup (asdf,
   direnv, copier — the only place this is documented); how to generate a
   service from either template; how to run `copier update`; how to change a
   template, including the rule that a copier question added to one language
   must be added to both; the versioning and tagging policy; what Phase 2
   and 3 will add.

6. **Top-level `AGENTS.md`**: for an agent maintaining *this* repo — the two
   governing principles, the `_common/` vs per-language split, the parity
   rules and how to run them, how to add a copier question to both
   languages, where the spec and ADRs live, and the deferral table with
   pointers to the ADRs that explain each.

7. **Generated `README.md`** — finish it: what the service is, quickstart,
   the Makefile targets, the mint mark, links to AGENTS.md, `/llms.txt`,
   `/openapi.json`, and the shared `docs/` files; the note that swapping the
   OTel exporter for a Collector is a config change; a `docker run` line for
   local Jaeger; and a justification for every dependency, per spec.

8. **Verify the direnv/asdf path end to end** on a clean shell: generate,
   `direnv allow`, `make run`, with no other manual setup. Both languages.

9. **`CHANGELOG.md`** per template, and tag `go-service/v0.1.0` and
   `python-service/v0.1.0`.

10. **Confirm the mint mark renders** in a service generated from the tagged
    template — and still degrades gracefully from an untagged checkout.

## Out of scope

Anything from the deferral table. Do not start Phase 2.

## Deliverables

- Complete `make parity` (8 checks) and `make verify`
- A drift-detection results table, one row per parity check
- A `copier update` walkthrough, verified in both languages
- Top-level README and AGENTS.md; generated README finished
- Tags `go-service/v0.1.0` and `python-service/v0.1.0`

## Acceptance criteria

- `make parity`, `make verify`, `make test`, and `make lint` all pass at the
  mint root.
- All eight parity checks have been individually proven to fail on the drift
  they target.
- `copier update` lands a template change into an existing generated service
  in both languages.
- A clean-shell run of generate → `direnv allow` → `make run` works with no
  other setup, both languages.
- A generated service's README shows the mint mark with the real tag.
- `make help` output from the two generated services is identical except for
  the service name.
- Every ADR from chunk 01 is still accurate, or has been superseded by a new
  ADR rather than edited in place.

## Flag back before finishing

- Any parity check that couldn't be made to fail on its target drift —
  that's a check that doesn't work, and it's worse than no check because it
  reads as a guarantee.
- Anything from spec § "Things to flag back to me" that got decided during
  implementation without an ADR.
- Your assessment of what Phase 1 got wrong or left awkward, while it's
  fresh. Phase 2 starts from this, and the honest version is more useful
  than a clean one.
