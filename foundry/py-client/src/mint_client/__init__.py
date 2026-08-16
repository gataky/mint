"""mint-client — the outbound HTTP client for Mint services.

The inbound half of a Mint service is a middleware chain that assigns a
correlation ID, continues a trace, records metrics, enforces a deadline and
returns RFC 9457 on failure. This package is the same chain pointing outwards,
so a request keeps all of it as it crosses to the next service::

    from mint_client import Client, UpstreamNotFoundError

    client = Client.for_peer(config.clients, "widget-svc", metrics=client_metrics)

    widget = await client.get("/widgets/abc", into=Widget, route="/widgets/{id}")

Everything the ecosystem depends on — ``traceparent``, ``X-Request-Id``, the
remaining request budget — is on that call without the call site mentioning it.

The design decisions worth knowing before changing anything are in each module's
docstring, and the short version is in the README:

* :mod:`mint_client.client` — the client itself
* :mod:`mint_client.errors` — why upstream errors are *not* domain errors
* :mod:`mint_client.context` — how the deadline and correlation ID are inherited
* :mod:`mint_client.config` — the schema, and why this package never reads it
* :mod:`mint_client.observability` — the three client metrics
* :mod:`mint_client.resilience` — the named, empty retry slot
"""

from __future__ import annotations

from mint_client.client import REQUEST_ID_HEADER, Client, Response
from mint_client.config import ClientsConfig, PeerConfig, PoolConfig, TimeoutConfig
from mint_client.context import bind_deadline, bind_request_id, remaining, request_id
from mint_client.duration import Duration, format_duration, parse_duration
from mint_client.errors import (
    ConnectError,
    DeadlineExceededError,
    MintClientError,
    ResponseValidationError,
    TransportError,
    UnknownPeerError,
    UpstreamClientError,
    UpstreamConflictError,
    UpstreamError,
    UpstreamForbiddenError,
    UpstreamInvalidError,
    UpstreamNotFoundError,
    UpstreamRateLimitedError,
    UpstreamServerError,
    UpstreamUnauthorizedError,
    UpstreamUnavailableError,
    UpstreamUnprocessableError,
)
from mint_client.observability import ClientMetrics
from mint_client.problem import Problem, ProblemDetail
from mint_client.resilience import NEVER, Attempt, RetryPolicy
from mint_client.version import __version__

__all__ = [
    "NEVER",
    "REQUEST_ID_HEADER",
    "Attempt",
    "Client",
    "ClientMetrics",
    "ClientsConfig",
    "ConnectError",
    "DeadlineExceededError",
    "Duration",
    "MintClientError",
    "PeerConfig",
    "PoolConfig",
    "Problem",
    "ProblemDetail",
    "Response",
    "ResponseValidationError",
    "RetryPolicy",
    "TimeoutConfig",
    "TransportError",
    "UnknownPeerError",
    "UpstreamClientError",
    "UpstreamConflictError",
    "UpstreamError",
    "UpstreamForbiddenError",
    "UpstreamInvalidError",
    "UpstreamNotFoundError",
    "UpstreamRateLimitedError",
    "UpstreamServerError",
    "UpstreamUnauthorizedError",
    "UpstreamUnavailableError",
    "UpstreamUnprocessableError",
    "__version__",
    "bind_deadline",
    "bind_request_id",
    "format_duration",
    "parse_duration",
    "remaining",
    "request_id",
]
