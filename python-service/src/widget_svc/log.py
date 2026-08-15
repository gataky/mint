"""The service logger, built on loguru.

Two tiers, selected by ``logging.format``:

``console``
    colorized, one line per event, for a human at a terminal (the default when
    env is local)
``json``
    one JSON object per line, for an aggregator

The contract with the outside world is the set of field *names*, not the bytes.
An aggregator parses JSON; it does not care about key order or whitespace. Every
line carries ``timestamp``, ``level``, ``msg``, ``service``, ``service_version``
and ``env``. Request-scoped lines add ``request_id``.

A line emitted inside a span also carries ``trace_id`` and ``span_id``, added by
a patcher rather than by call sites, and omitted entirely when there is no span.

Request-scoped fields ride on ``logger.contextualize``, which is contextvar
based — the same mechanism OpenTelemetry uses. No logger has to be threaded
through call signatures.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TextIO

from loguru import logger
from opentelemetry import trace

if TYPE_CHECKING:
    # loguru exports these from its stub only; they do not exist at runtime.
    from loguru import Message, Record

__all__ = ["configure", "logger"]

# Reserved field names. Call sites do not set these; they are bound once, at
# startup, or by the request middleware.
KEY_TIME = "timestamp"
KEY_LEVEL = "level"
KEY_MESSAGE = "msg"
KEY_SERVICE = "service"
KEY_SERVICE_VERSION = "service_version"
KEY_ENV = "env"
KEY_REQUEST_ID = "request_id"
KEY_TRACE_ID = "trace_id"
KEY_SPAN_ID = "span_id"

#: loguru's level names are not slog's. The *value* of the level field is
#: something an aggregator queries on, so it is normalised rather than left to
#: differ between the two services.
_LEVEL_ALIASES = {
    "WARNING": "warn",
    "CRITICAL": "error",
    "SUCCESS": "info",
    "TRACE": "debug",
}

#: Our config vocabulary, mapped onto loguru's.
_LEVELS = {"debug": "DEBUG", "info": "INFO", "warn": "WARNING", "error": "ERROR"}


def configure(
    *,
    level: str = "info",
    fmt: str = "console",
    service: str = "",
    service_version: str = "",
    env: str = "",
    stream: TextIO | None = None,
) -> None:
    """Install the log tier. Replaces any previously installed sink."""
    out = stream if stream is not None else sys.stdout

    logger.remove()

    # These ride on every line, including ones emitted before any request.
    # The patcher adds the trace fields to every record, so no call site can
    # forget them.
    logger.configure(
        extra={
            KEY_SERVICE: service,
            KEY_SERVICE_VERSION: service_version,
            KEY_ENV: env,
        },
        patcher=_add_trace_fields,
    )

    if fmt == "json":
        logger.add(
            _json_sink(out),
            level=_LEVELS.get(level, "INFO"),
            format="{message}",
            colorize=False,
        )
    else:
        logger.add(
            out,
            level=_LEVELS.get(level, "INFO"),
            format=_console_format,
            # loguru decides colour by asking whether the stream is a tty, but
            # does not honour NO_COLOR. Left alone it writes ANSI escapes into a
            # redirected file whenever colorize is forced on.
            colorize=_use_colour(out),
        )


def _add_trace_fields(record: Record) -> None:
    """Add trace_id and span_id from the active span.

    **The fields are omitted entirely when there is no span** — never empty,
    never fabricated. An empty trace_id in an aggregator is worse than an absent
    one: it looks like a trace that exists and cannot be found.
    """
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return

    # Hex, zero-padded, matching the Go service and the W3C traceparent format.
    record["extra"][KEY_TRACE_ID] = format(context.trace_id, "032x")
    record["extra"][KEY_SPAN_ID] = format(context.span_id, "016x")


def level_name(loguru_level: str) -> str:
    """Normalise a loguru level name to the shared vocabulary."""
    return _LEVEL_ALIASES.get(loguru_level, loguru_level.lower())


def _json_sink(out: TextIO) -> Callable[[Message], None]:
    """One JSON object per line, with the reserved fields first.

    loguru's own ``serialize=True`` wraps everything in a ``{"text":…,
    "record":{…}}`` envelope, which is not the flat shape the Go service emits.
    Fifteen lines here is the cost of the two services being queryable with one
    expression.
    """

    def sink(message: Message) -> None:
        record = message.record
        event: dict[str, Any] = {
            KEY_TIME: record["time"].isoformat(),
            KEY_LEVEL: level_name(record["level"].name),
            KEY_MESSAGE: record["message"],
        }
        event.update(record["extra"])

        if record["exception"] is not None:
            event["exception"] = _format_exception(record["exception"])

        out.write(json.dumps(event, default=str) + "\n")
        out.flush()

    return sink


def _console_format(record: Record) -> str:
    """Build the console format string for one record.

    Returning a format string — rather than the finished line — is loguru's
    contract for a callable formatter; it still does the colour markup and the
    field substitution.
    """
    level = level_name(record["level"].name)

    extras = " ".join(f"{key}={_render(value)}" for key, value in record["extra"].items())
    line = f"<green>{{time:HH:mm:ss.SSS}}</green> <level>{level}</level> <level>{{message}}</level>"
    if extras:
        # Braces in a value would otherwise be read as format placeholders, and
        # angle brackets as colour markup.
        line += " <dim>" + _escape(extras) + "</dim>"
    return line + "\n{exception}"


def _render(value: Any) -> str:
    text = str(value)
    return f'"{text}"' if " " in text else text


def _escape(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}").replace("<", r"\<")


def _format_exception(exception: Any) -> str:
    import traceback

    return "".join(traceback.format_exception(exception.type, exception.value, exception.traceback))


def _use_colour(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return bool(getattr(stream, "isatty", lambda: False)())
