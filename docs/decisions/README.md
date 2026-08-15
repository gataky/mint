# Architecture decision records

Every generated service inherits these decisions. An env var prefix or a
metric naming scheme is nearly free to choose once and expensive to change
after forty services exist — so the reasoning has to outlive the
conversation that produced it.

## When to write one

- Anything in `prompt.md` § "Things to flag back to me"
- A call the spec doesn't dictate and the next person would plausibly make
  differently
- A deliberate *non*-decision — something deferred, with the seam that keeps
  it cheap to add later (see 0004, 0005)
- A spike that contradicted an assumption the spec was built on

Not for: choices the spec already makes, or ones with an obvious default and
no tradeoff.

## How

Copy [0000-template.md](0000-template.md), take the next free number.
Supersede rather than edit — an ADR is a record of what was decided *then*,
and rewriting it destroys the only evidence of why the code looks the way it
does. Mark the old one superseded and link forward.

## Index

| # | decision | status |
| --- | --- | --- |
| _(chunk 01 populates this)_ | | |
