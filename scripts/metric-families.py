#!/usr/bin/env python3
"""Reduce a Prometheus exposition to (family -> sorted label keys), as JSON.

Reads the exposition on stdin and prints only the families Mint owns. Comparing
parsed families rather than raw text is deliberate: Python renders le="1.0"
against Go's le="1", orders families differently, and exposes a different set of
runtime collectors. None of that is observable from outside the service.

Exits non-zero if an owned family is missing, so a comparison can never pass by
finding nothing on both sides.
"""

from __future__ import annotations

import json
import re
import sys

OWNED = {
    "http_server_requests_total",
    "http_server_request_duration_seconds",
    "http_server_active_requests",
    "target_info",
}

SAMPLE = re.compile(r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>.*)\})?\s")
LABEL_KEY = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=")
# Histograms expand into _bucket/_sum/_count samples; fold them back.
SUFFIX = re.compile(r"_(bucket|sum|count)$")


def main() -> int:
    families: dict[str, set[str]] = {}

    for line in sys.stdin:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        match = SAMPLE.match(line)
        if match is None:
            continue

        base = SUFFIX.sub("", match["name"])
        if base not in OWNED:
            continue

        keys = {key for key in LABEL_KEY.findall(match["labels"] or "") if key != "le"}
        families.setdefault(base, set()).update(keys)

    missing = OWNED - families.keys()
    if missing:
        print(f"missing owned metric families: {sorted(missing)}", file=sys.stderr)
        return 1

    print(json.dumps({name: sorted(keys) for name, keys in sorted(families.items())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
