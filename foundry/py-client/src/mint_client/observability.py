"""The client-side mirror of the service's three HTTP metrics.

Same names, same shape, ``client`` where the service says ``server``::

    http_client_requests_total{method,peer,status}
    http_client_request_duration_seconds{method,peer,status}
    http_client_active_requests{method,peer}

**The registry comes from the service; the metric definitions come from here.**
That division is the whole reason this is a shared library rather than a
snippet in each service: a registry per service is required (the process-global
one cannot be built twice, so two services could not be constructed in one test
session), but a *different metric name* per service would mean no dashboard
could ever span two of them.

``peer``, never a host and never a URL
--------------------------------------
The label is the logical service name, exactly as ``route`` on the server side
is the route template and never the concrete path. A URL as a label is the same
unbounded-cardinality mistake in outbound clothing: one call per widget ID would
mint one series per widget ID.

The ``<error>`` status
----------------------
A call that never got a response has no status code, and inventing one would be
worse than admitting it — a synthetic 503 is indistinguishable in a dashboard
from a real one the peer actually sent. The sentinel follows the convention the
server side already set with ``<unmatched>``: angle brackets cannot occur in a
real value, so the sentinel is unambiguous.

Which *kind* of transport failure it was — timeout, connection refused, DNS —
is on the span as ``error.type``, not in a metric label. That is a deliberate
v1 limit and is noted in the README.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, disable_created_metrics

__all__ = ["ERROR_STATUS", "ClientMetrics"]

#: The ``status`` label for a call that produced no response.
ERROR_STATUS = "<error>"

#: OpenTelemetry's advisory buckets for http.client.request.duration. Declared
#: literally, for the same reason the server side declares its own: a library
#: default that changes on upgrade silently re-buckets every historical series.
DURATION_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.25,
    0.5,
    0.75,
    1.0,
    2.5,
    5.0,
    7.5,
    10.0,
)


class ClientMetrics:
    """The outbound HTTP instruments, registered into the service's registry.

    Construct one per service and share it across every :class:`Client`; the
    ``peer`` label is what separates them. Constructing one per client would
    fail on the second, because a registry rejects duplicate metric names.
    """

    def __init__(self, registry: CollectorRegistry) -> None:
        # Matches the server side: every counter is otherwise shadowed by a
        # _created gauge that nothing consumes.
        disable_created_metrics()  # type: ignore[no-untyped-call]

        self.requests = Counter(
            "http_client_requests",  # _total is appended by the client library
            "Total HTTP requests sent to upstream services.",
            labelnames=("method", "peer", "status"),
            registry=registry,
        )
        self.duration = Histogram(
            "http_client_request_duration_seconds",
            "Upstream HTTP request duration in seconds.",
            labelnames=("method", "peer", "status"),
            buckets=DURATION_BUCKETS,
            registry=registry,
        )
        # Unlike the server's in-flight gauge, this one *can* carry the peer:
        # the destination is known before the call starts, whereas a route
        # template is not known until the router has run.
        self.active = Gauge(
            "http_client_active_requests",
            "Upstream HTTP requests currently in flight.",
            labelnames=("method", "peer"),
            registry=registry,
        )

    def request_started(self, method: str, peer: str) -> None:
        """Increment the in-flight gauge."""
        self.active.labels(method, peer).inc()

    def request_finished(self, method: str, peer: str, status: str, elapsed: float) -> None:
        """Decrement the in-flight gauge and record the outcome.

        ``status`` is a string so :data:`ERROR_STATUS` can occupy the same label
        as a real code.
        """
        self.active.labels(method, peer).dec()
        self.requests.labels(method, peer, status).inc()
        self.duration.labels(method, peer, status).observe(elapsed)
