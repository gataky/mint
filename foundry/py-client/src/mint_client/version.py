"""The package version, in a module of its own.

``client.py`` puts it in the User-Agent and in the tracer's instrumentation
scope. Reading it from ``__init__`` would be circular, since ``__init__``
imports the client.
"""

from __future__ import annotations

__version__ = "0.1.0"
