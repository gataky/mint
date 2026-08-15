"""In-memory repository implementations, backed by a dict.

These are the real implementations at runtime and the fakes in tests — there is
only one, so the thing the tests exercise is the thing that runs.

One module per resource, mirroring ``service/``.
"""
{#- The whitespace control is load-bearing: this block ends the file, so a
    plain {% endif %} would leave a blank line at EOF that ruff format rejects. #}
{%- if include_examples %}

from {@ package_name @}.repository.memory.orders import Orders
from {@ package_name @}.repository.memory.widgets import Widgets

__all__ = ["Orders", "Widgets"]
{%- endif %}
