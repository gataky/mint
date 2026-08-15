# 0014 — The Python entrypoint constructs its own Servers and owns its signals

**Status:** accepted (2026-08-14)
**Date:** 2026-08-14
**Chunk:** 02 (recorded); implemented across 04 and 06
**Reconciles:** [0008](0008-serve-api-and-admin-on-separate-ports.md) ×
[0010](0010-use-structlog-for-python-logging.md)

## Context

Two accepted ADRs, written in parallel, give incompatible instructions for
the same six lines of Python.

[ADR 0010](0010-use-structlog-for-python-logging.md) requires
`uvicorn.run(app, log_config=None, access_log=False)`. Both kwargs are
load-bearing: uvicorn's default `log_config` is a full `dictConfig` that
installs handlers with `propagate: False`, so a "JSON-only" service emits
nine plain-text lines and one JSON line per request lifecycle. Verified on
uvicorn 0.52.3:

```
Config.log_config default = {... 'loggers': {'uvicorn': {'propagate': False},
                                             'uvicorn.access': {'propagate': False}}}
Config.access_log default = True
```

[ADR 0008](0008-serve-api-and-admin-on-separate-ports.md) requires **two**
listeners built from one slice, with `capture_signals` neutralized so the
composition root owns SIGTERM. It measured the failure when it isn't:
`uvicorn.Server.serve()` wraps itself in `capture_signals()`, which installs
process-global handlers, so a second server's registration replaces the
first's and the process dies **exit 143** before either drains.

`uvicorn.run()` constructs exactly one `Server` and calls `serve()` on it. It
cannot produce two, and it gives no handle on which to neutralize
`capture_signals`. The two ADRs cannot both be followed literally.

## Decision

**The composition root builds `uvicorn.Config` and `uvicorn.Server`
explicitly, one pair per listener, and owns its own signal handling.**
`uvicorn.run()` is not used in a finished Mint service.

Every `Config` carries `log_config=None` and `access_log=False` — the two
kwargs move from `run()` to `Config`, which accepts both (verified above).
Every `Server` gets `capture_signals` neutralized. The composition root
installs one SIGTERM/SIGINT handler and drives the drain sequence across the
whole slice.

**Chunk 04 may ship `uvicorn.run(...)` as an interim step**, because chunk 04
delivers logging and has no second listener to run yet. Chunk 06 replaces it.
That hand-off is the risky moment and is called out in both chunk files:
**`log_config=None` and `access_log=False` must survive the move into
`Config`.** Losing either silently restores uvicorn's own handlers, and the
symptom — a service that logs correctly in tests and in two formats in
production — appears nowhere near the change that caused it.

## Alternatives considered

**Keep `uvicorn.run()` and collapse to a single port.** Resolves the conflict
by deleting one side of it, and ADR 0008's collapse path already supports
`admin_port == port`. Rejected because it makes the *default* configuration
the one that can't report readiness while draining — ADR 0008's whole
argument — to avoid six lines of setup.

**Run the admin listener on a second thread with its own event loop.**
Sidesteps the signal collision, since only one loop would call
`capture_signals`. Rejected: two event loops in one process is a much larger
concurrency claim than two servers on one loop, and it puts the metrics
registry and health registry across a thread boundary for no gain.

**Neutralize `capture_signals` but keep `run()` for the API listener.**
`run()` gives no handle on the `Server` it builds, so there is nothing to
neutralize. Not viable.

**Patch `uvicorn.Server.serve` globally.** Rejected — a monkeypatch in every
generated service, to avoid using a public API as documented.

## Consequences

Python's composition root is a little longer than a tutorial FastAPI app, and
that difference is exactly where a reader should look: it is where the port
split, the drain ordering, and the logging ownership live. It gets a comment
naming this ADR.

**The Go and Python roots converge in shape rather than diverging.** Go was
always going to construct `http.Server` values explicitly and own its
signals; this makes Python do the same thing for the same reasons, which is
better for the parity story than `uvicorn.run()` would have been.

`make run` still invokes `python -m <pkg>` and never the `uvicorn` CLI — the
CLI calls `configure_logging()` before importing the app, so no in-app
configuration can reclaim the handlers. That constraint is unchanged and
independent of this decision.

The verify harness must send SIGTERM against the **split** configuration.
Under a collapsed single listener the signal race cannot appear, so testing
only that path would pass while shipping the bug.
