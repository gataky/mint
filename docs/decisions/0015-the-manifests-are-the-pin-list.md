# 0015 — The template manifests are the pin list, not a table in a document

**Status:** accepted (2026-08-14)
**Date:** 2026-08-14
**Chunk:** 02
**Amends:** [0011](0011-pinned-toolchain-versions.md) (its role, not its
content) · **Absorbs:** [0012](0012-pin-lmittmann-tint-for-go-console-logging.md)'s
awkwardness

## Context

ADR 0011 pinned the toolchain and produced a version table. Standing rule 5
in `tasks/README.md` then made that table *the* pin list — the thing an
implementing chunk consults and a reviewer checks against.

It has been authoritative for one chunk and has fallen out of date twice:

- **`lmittmann/tint v1.2.0`.** ADR 0010 offered a colour dependency pending a
  human decision; the decision was made, 0011 had been written in parallel
  and had no row for it. ADR 0012 exists partly to be that row.
- **`hatchling==1.32.0`.** The Python build backend. Nobody decided to omit
  it; it simply wasn't a question anyone asked during chunk 01, and it became
  real the moment a `pyproject.toml` existed.

Neither omission was a mistake in reasoning. Both are the same structural
problem: **a version table in a markdown document is a second copy of a fact
whose first copy is executable.** `go.mod`, `pyproject.toml`, `uv.lock` and
`.tool-versions` are what the build actually reads. A table restating them
drifts the instant a chunk adds a dependency, and it drifts *silently*,
because nothing executes it.

This is exactly the failure the spec's first principle names, committed by
our own process rather than by the templates.

## Decision

**The template's own manifests are the authoritative pin list**:
`.tool-versions`, `go.mod` (including `tool` directives), `pyproject.toml`,
and `uv.lock`. To know what a version is, read the file the build reads.

**ADR 0011 keeps its policy and its historical record** — pin exactly, never
resolve "latest" at generation time, bump deliberately as a template release
— and its table is retained as *what was decided in chunk 01*, not as a live
index. It is not edited when a dependency is added.

**A chunk that adds a dependency states the pin in its handoff** and does not
need a new ADR to do so. An ADR is for the *choice* — "tint rather than zap,
and here is why" is worth recording; "the build backend is hatchling" is not.
ADR 0012 remains valuable for its argument and its evidence; it simply should
not have needed to exist in order to register a version number.

Standing rule 5 in `tasks/README.md` changes accordingly.

## Alternatives considered

**Keep the table and add a parity check that it matches the manifests.**
The obvious mechanical fix, and it would work. Rejected because it spends a
check, and every future maintainer's attention, defending a duplicate that
has no reason to exist. The principle says remove the second copy, not
automate its upkeep. Reach for a check when two representations are both
genuinely needed; here one of them isn't.

**Require an amending ADR per new pin.** This is the status quo, and its cost
is now measured: two ADRs' worth of ceremony in one chunk, one of which
(0012) is carrying a real argument and a spurious clerical duty at the same
time. It also creates a bad incentive — a chunk that needs a small dependency
is nudged toward avoiding it rather than recording it.

**Generate the table from the manifests in `make agents-docs`.** Genuinely
appealing, and consistent with how `openapi.json` and `llms.txt` are handled.
Rejected for now because the consumer is a human reading an ADR, and ADRs are
supposed to be immutable records of a moment. A generated, mutating table
inside a historical document is a category error. Revisit if the top-level
README ever wants a live pin table — that is a reasonable place for one.

## Consequences

Reviewing "are we on the right versions" means reading four manifest files
instead of one table. That is a real ergonomic loss, and it is the price of
those four files being the only place the answer lives.

`hatchling==1.32.0` needs no ADR. Neither will the next dependency.

ADR 0011's table becomes a snapshot of 2026-08-14 rather than a live index.
Anyone reading it later should be able to tell — this ADR is linked from it
via the index in `README.md`, and 0011's own status line is unchanged because
its *decisions* are all still in force.
