# AGENTS.md contract

> **Source of truth** for what a generated service's `AGENTS.md` must
> contain. Both language templates render their AGENTS.md from this, so an
> agent opening a Go service and one opening a Python service find the same
> sections in the same order.
>
> **Status: stub.** Filled in by chunk [09](../tasks/09-discovery.md).

## Required sections

_Chunk 09._

## The generated command block

_Chunk 09. Written by `make agents-docs` from the Makefile's own `##`
comments — neither restated by hand (drift) nor merely linked (useless to an
agent that then has to go read a Makefile)._

## "Don't do this" boundaries

_Chunk 09. At minimum: the service layer never imports `net/http` or FastAPI
request types; nothing outside `internal/config` reads an env var; never
label a metric with an unbounded value._
