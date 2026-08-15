"""In-memory repository implementations, backed by a dict.

These are the real implementations at runtime and the fakes in tests — there is
only one, so the thing the tests exercise is the thing that runs.

One module per resource, mirroring ``service/``.
"""

from widget_svc.repository.memory.orders import Orders
from widget_svc.repository.memory.widgets import Widgets

__all__ = ["Orders", "Widgets"]
