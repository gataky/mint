# Logging

> **Source of truth** for this service's log schema. Both of Mint's languages
> emit exactly the field set defined here; Mint's `make parity` boots a
> generated service in each language and diffs their emitted keys against this
> document, so a field that is not written down here does not exist.
>
> **Status: stub.** Filled in by Mint chunk 04. Until then the service prints
> one plain line at startup and nothing else — there is deliberately no
> logging configuration to inherit yet.

## Reserved fields

_Mint chunk 04. The reserved block — timestamp, level, message, service,
service_version, env, trace_id, span_id — with types and semantics. A call
site that passes one of these keys has its value dropped, not honoured._

## The two tiers

_Mint chunk 04. Tier 1 is the human console renderer for local development;
tier 2 is one JSON object per line for everything else._

## Redaction

_Mint chunk 04. Exact match on the lowercased key, never a substring._

## Free-form keys

_Mint chunk 04. `snake_case`, in call order, after the reserved block._
