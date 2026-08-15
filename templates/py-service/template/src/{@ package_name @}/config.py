"""Configuration: the only place in the service that reads the environment or a file.

Precedence, lowest to highest::

    built-in defaults  <  config/config.yaml  <  config/config.local.yaml  <  environment

Environment variables are named ``{@ env_prefix @}_`` + the config path upper-cased, with
``__`` between levels and the key's own underscores preserved::

    server.read_timeout  ->  {@ env_prefix @}_SERVER__READ_TIMEOUT
    logging.format       ->  {@ env_prefix @}_LOGGING__FORMAT

Single-underscore nesting is deliberately not used: it cannot distinguish
``server.read_timeout`` from ``server.read.timeout``. The constant ``{@ env_prefix @}_``
prefix is deliberate too — Kubernetes injects ``{SVCNAME}_PORT`` into every pod,
so a service-name prefix would collide with it.
"""

from __future__ import annotations

import os
import re
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal

import yaml
from pydantic import BeforeValidator, Field, PlainSerializer
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

ENV_PREFIX = "{@ env_prefix @}_"

# Where config files are looked for, in increasing order of precedence.
CONFIG_FILES = (Path("config/config.yaml"), Path("config/config.local.yaml"))

OTLP_ENDPOINT_KEY = "observability.tracing.otlp_endpoint"

#: The single exception to the {@ env_prefix @}_ prefix rule. It is enumerated explicitly —
#: never read as a wildcard OTEL_* lookup — so every value reaching the config
#: still has one named source.
#:
#: Mint defers on OTLP *transport* and owns *identity*: OTEL_SERVICE_NAME and
#: OTEL_RESOURCE_ATTRIBUTES are deliberately ignored, because logs and spans
#: disagreeing about ``service`` or ``env`` would break the error-to-trace path.
OTLP_ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"

_DURATION_PATTERN = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h)")
_DURATION_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


def _parse_duration(value: Any) -> Any:
    """Accept Go-style duration strings so both services read the same YAML.

    ``"15s"``, ``"1m30s"``, ``"500ms"``. A bare number is seconds.
    """
    if isinstance(value, str):
        matches = _DURATION_PATTERN.findall(value.strip())
        if matches:
            seconds = sum(float(amount) * _DURATION_UNITS[unit] for amount, unit in matches)
            return timedelta(seconds=seconds)
    if isinstance(value, int | float):
        return timedelta(seconds=value)
    return value


def format_duration(value: timedelta) -> str:
    """Render a duration the way it is written in YAML, not as a raw float."""
    seconds = value.total_seconds()
    if seconds == 0:
        return "0s"
    if seconds < 1:
        return f"{seconds * 1000:g}ms"

    # Go's time.Duration.String() renders 60s as "1m0s", not "1m". Matching it
    # keeps `make config` output comparable between the two services.
    parts = []
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        parts.append(f"{hours:g}h")
    if minutes or parts:
        parts.append(f"{minutes:g}m")
    parts.append(f"{secs:g}s")
    return "".join(parts)


Duration = Annotated[
    timedelta,
    BeforeValidator(_parse_duration),
    PlainSerializer(format_duration, return_type=str),
]

Env = Literal["local", "dev", "staging", "prod"]
LogLevel = Literal["debug", "info", "warn", "error"]
LogFormat = Literal["console", "json"]


class Service(BaseSettings):
    """Identifies this service to logs, traces and metrics."""

    name: str = Field(default="{@ service_name @}", min_length=1)
    version: str = "0.1.0"
    owner: str = "{@ service_owner @}"


class Server(BaseSettings):
    """HTTP listener settings.

    Every timeout is non-zero by default: a zero ``read_header_timeout`` is a
    slowloris vector.
    """

    port: int = Field(default={@ port @}, ge=1024, le=65535)
    admin_port: int = Field(default={@ admin_port @}, ge=1024, le=65535)

    read_header_timeout: Duration = Field(default=timedelta(seconds=5), gt=timedelta(0))
    read_timeout: Duration = Field(default=timedelta(seconds=15), gt=timedelta(0))
    write_timeout: Duration = Field(default=timedelta(seconds=15), gt=timedelta(0))
    idle_timeout: Duration = Field(default=timedelta(seconds=60), gt=timedelta(0))

    #: Per-request deadline handlers work against.
    request_timeout: Duration = Field(default=timedelta(seconds=10), gt=timedelta(0))
    #: Bounds the drain on SIGTERM.
    shutdown_timeout: Duration = Field(default=timedelta(seconds=15), gt=timedelta(0))


class Logging(BaseSettings):
    """Log tier and verbosity."""

    level: LogLevel = "info"
    format: LogFormat = "console"


class Tracing(BaseSettings):
    """The OpenTelemetry tracer provider."""

    #: Turns span creation off entirely. When false there is no trace context,
    #: so log lines carry no trace_id.
    enabled: bool = True

    #: The collector to export to, e.g. http://localhost:4318. Empty installs a
    #: no-op exporter: spans are still created, so logs still correlate, but
    #: nothing leaves the process and a fresh `make run` emits no
    #: connection-refused retries.
    otlp_endpoint: str = ""

    #: Head sampling ratio, applied only to traces this service starts. A
    #: sampling decision made upstream is respected.
    sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)


class Observability(BaseSettings):
    """Tracing configuration.

    Metrics need none: they are always collected and always served on the admin
    port.
    """

    tracing: Tracing = Tracing()


class Config(BaseSettings):
    """The whole of the service's configuration.

    Validation reports every invalid field at once rather than stopping at the
    first — pydantic does this natively — so a misconfigured deploy is fixed in
    one pass instead of four.
    """

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_nested_delimiter="__",
        # An unknown key in YAML is a typo worth failing on. An unknown {@ env_prefix @}_
        # variable in the environment is not ours to police — but pydantic
        # applies this to both, and failing to boot because someone exported a
        # stray variable is the worse outcome.
        extra="ignore",
        nested_model_default_partial_update=True,
    )

    env: Env = "local"
    service: Service = Service()
    server: Server = Server()
    logging: Logging = Logging()
    observability: Observability = Observability()

    #: Set by :func:`load`; records which source supplied each key.
    sources: ClassVar[dict[str, str]] = {}

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Return exactly the sources this service supports, highest priority first.

        pydantic-settings defaults to a four-source chain that includes
        ``.env`` files and Docker secrets. Left alone, a ``.env`` file silently
        beats YAML. Both are dropped here: ``.env`` is direnv's business, loaded
        into the environment before the process starts, never read by the
        application.
        """
        del dotenv_settings, file_secret_settings  # deliberately unused

        return (init_settings, env_settings, YamlSource(settings_cls))

    def split_listeners(self) -> bool:
        """Whether the API and admin servers need separate listeners."""
        return self.server.port != self.server.admin_port


class YamlSource(PydanticBaseSettingsSource):
    """Reads the YAML config files, later files overlaying earlier ones.

    A missing file is not an error: the service is meant to boot with none of
    them.
    """

    def __init__(self, settings_cls: type[BaseSettings], files: tuple[Path, ...] | None = None):
        super().__init__(settings_cls)
        self.files = CONFIG_FILES if files is None else files

    def __call__(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for path in self.files:
            if not path.is_file():
                continue
            loaded = yaml.safe_load(path.read_text()) or {}
            _deep_merge(merged, loaded)
        return merged

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        # Required by the base class but unused: __call__ supplies the whole
        # mapping in one go.
        raise NotImplementedError


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> None:
    """Merge overlay into base, descending into nested mappings."""
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def load(files: tuple[Path, ...] | None = None) -> Config:
    """Build the configuration and record where each value came from."""
    paths = CONFIG_FILES if files is None else files

    class _Config(Config):
        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            del dotenv_settings, file_secret_settings
            return (init_settings, env_settings, YamlSource(settings_cls, paths))

    config = _Config()
    sources = _resolve_sources(paths)

    # The one ecosystem variable this service honours. "Unset" means empty, not
    # absent: the model always supplies a default for this key, so there is no
    # "missing" state to test for.
    endpoint = os.environ.get(OTLP_ENDPOINT_ENV, "")
    if not config.observability.tracing.otlp_endpoint and endpoint:
        config.observability.tracing.otlp_endpoint = endpoint
        sources[OTLP_ENDPOINT_KEY] = f"env:{OTLP_ENDPOINT_ENV}"

    Config.sources = sources
    return config


def _resolve_sources(paths: tuple[Path, ...]) -> dict[str, str]:
    """Map each dotted config key to the source that supplied its winning value.

    This re-reads the layers rather than asking pydantic, which does not report
    provenance. The values themselves always come from the validated Config.
    """
    sources: dict[str, str] = {}

    for path in paths:
        if not path.is_file():
            continue
        loaded = yaml.safe_load(path.read_text()) or {}
        for key in _flatten(loaded):
            sources[key] = str(path)

    for name in os.environ:
        if not name.startswith(ENV_PREFIX):
            continue
        key = name[len(ENV_PREFIX) :].lower().replace("__", ".")
        sources[key] = f"env:{name}"

    return sources


def _flatten(mapping: dict[str, Any], prefix: str = "") -> list[str]:
    """Flatten a nested mapping into dotted keys."""
    keys: list[str] = []
    for key, value in mapping.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict):
            keys.extend(_flatten(value, f"{dotted}."))
        else:
            keys.append(dotted)
    return keys


def render(config: Config) -> str:
    """The effective configuration, one key per line, annotated with its source.

    This is what ``make config`` and ``--print-config`` show.

    There are no secret-typed fields yet. When one is added, mask it here — use
    pydantic's ``SecretStr`` so masking is a property of the type rather than of
    every call site.
    """
    dumped = config.model_dump(mode="json")
    flat = {key: _render_value(_lookup(dumped, key)) for key in _flatten(dumped)}

    width = max(len(key) for key in flat)
    value_width = max(len(value) for value in flat.values())

    lines = []
    for key in sorted(flat):
        source = Config.sources.get(key, "default")
        lines.append(f"{key:<{width}}  {flat[key]:<{value_width}}  # {source}")
    return "\n".join(lines)


def _render_value(value: Any) -> str:
    """Render one value the way the Go service renders it.

    Python would otherwise print ``True`` where Go prints ``true``, and ``1.0``
    where Go prints ``1``. `make config` output is read side by side often
    enough for that to be worth a few lines.
    """
    if isinstance(value, bool):  # before int: bool is a subclass of int
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _lookup(mapping: dict[str, Any], dotted: str) -> Any:
    value: Any = mapping
    for part in dotted.split("."):
        value = value[part]
    return value
