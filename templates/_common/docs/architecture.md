# Architecture

> **Source of truth** for this service's three-layer architecture, the
> operation registry, the error contract, the middleware chain, and the
> runtime lifecycle. This file is minted from Mint's `templates/_common/`, so
> the Go and Python versions of it are the same file — a rule stated here
> holds for both languages, and Mint's `make parity` checks that they obey it.
>
> **Status: stub.** Each section names the Mint chunk that fills it in. Run
> `copier update` once that chunk has shipped. An empty section below is not a
> missing file — it is work Mint has not done yet.
>
> **Where to edit it.** This file is authored in Mint, at
> `templates/_common/docs/architecture.md`; Mint's own `docs/architecture.md`
> is a symlink to it, so there is exactly one copy of these facts. In a
> generated service, edit it only to record a decision *that service* has made
> which departs from the template — everything else belongs upstream, or the
> next `copier update` conflicts with it.

## The three layers

_Mint chunk 07._

Transport parses and serializes, service decides, repository talks to the
outside world. The dependency arrows only ever point inward.

## The operation registry

_Mint chunk 07. The single authoring location for an operation — the router,
`openapi.json` and `llms.txt` all read it rather than restating it. Do not add
a field to it that only an HTTP router could consume._

## Error contract

_Mint chunk 05._

## Middleware order

_Mint chunk 06._

## Runtime lifecycle

_Mint chunk 06._

## Ports

_Mint chunk 06 wires the second listener; the port numbers are already
recorded in `.copier-answers.yml`._

The API port serves the application. The admin port serves `/metrics`,
`/healthz` and `/readyz`, and defaults to the API port + 1000. Setting them
equal collapses everything onto one listener, which is a supported
configuration rather than an error.

The admin port is a **routing and lifecycle boundary, not a security
boundary**: any pod that can reach the pod IP can reach every container port
on it. Keeping `/metrics` private is NetworkPolicy's job. What the split
actually buys is that readiness and metrics stay answerable while the API
listener is draining.

## Observability wiring

_Mint chunk 08._
