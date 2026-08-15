"""Configuration: precedence, validation, and provenance."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from {@ package_name @}.config import Config, format_duration, load, render


def write_yaml(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body)
    return path


def test_load_with_no_sources_uses_defaults(tmp_path: Path) -> None:
    # The service must boot with no config file and no environment at all.
    config = load(files=(tmp_path / "does-not-exist.yaml",))

    assert config.model_dump() == Config().model_dump()


def test_environment_beats_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_yaml(tmp_path, "config.yaml", "logging:\n  level: info\n")
    monkeypatch.setenv("{@ env_prefix @}_LOGGING__LEVEL", "debug")

    assert load(files=(path,)).logging.level == "debug"


def test_later_yaml_file_beats_earlier(tmp_path: Path) -> None:
    base = write_yaml(tmp_path, "config.yaml", "logging:\n  level: info\n  format: console\n")
    local = write_yaml(tmp_path, "config.local.yaml", "logging:\n  level: debug\n")

    config = load(files=(base, local))

    assert config.logging.level == "debug"
    # The local file said nothing about format, so the base file still holds.
    assert config.logging.format == "console"


def test_double_underscore_separates_levels(monkeypatch: pytest.MonkeyPatch) -> None:
    # Single-underscore nesting cannot distinguish server.read_timeout from
    # server.read.timeout. The key's own underscores are preserved; only "__"
    # descends a level.
    monkeypatch.setenv("{@ env_prefix @}_SERVER__READ_TIMEOUT", "42s")

    assert load(files=()).server.read_timeout == timedelta(seconds=42)


def test_unprefixed_environment_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    # Kubernetes injects {SVCNAME}_PORT into every pod. Nothing without the
    # {@ env_prefix @}_ prefix may reach the configuration.
    monkeypatch.setenv("PORT", "1234")
    monkeypatch.setenv("WIDGET_SVC_PORT", "tcp://10.0.162.149:8080")

    assert load(files=()).server.port == Config().server.port


def test_dotenv_files_are_not_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # pydantic-settings defaults to a source chain that includes .env, which
    # would silently beat YAML. .env is direnv's business, never the app's.
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("{@ env_prefix @}_LOGGING__LEVEL=error\n")
    path = write_yaml(tmp_path, "config.yaml", "logging:\n  level: debug\n")

    assert load(files=(path,)).logging.level == "debug"


def test_validation_reports_every_problem_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("{@ env_prefix @}_ENV", "bogus")
    monkeypatch.setenv("{@ env_prefix @}_SERVER__PORT", "99")
    monkeypatch.setenv("{@ env_prefix @}_LOGGING__LEVEL", "chatty")

    with pytest.raises(ValidationError) as raised:
        load(files=())

    # Stopping at the first problem means three deploy-fix cycles instead of one.
    reported = {".".join(str(p) for p in error["loc"]) for error in raised.value.errors()}
    assert reported == {"env", "server.port", "logging.level"}


@pytest.mark.parametrize("env", ["local", "dev", "staging", "prod"])
def test_validation_accepts_every_declared_env(env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("{@ env_prefix @}_ENV", env)

    assert load(files=()).env == env


def test_invalid_configuration_is_a_startup_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("{@ env_prefix @}_ENV", "production")  # the valid value is "prod"

    with pytest.raises(ValidationError):
        load(files=())


def test_render_annotates_the_winning_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_yaml(tmp_path, "config.yaml", "logging:\n  format: json\n")
    monkeypatch.setenv("{@ env_prefix @}_LOGGING__LEVEL", "debug")

    printed = render(load(files=(path,)))

    assert "env:{@ env_prefix @}_LOGGING__LEVEL" in printed  # set by the environment, and says so
    assert str(path) in printed  # set by the file, and names it
    assert "# default" in printed  # untouched keys say that
    # Durations render readably, not as a float count of seconds.
    assert re.search(r"server\.read_timeout\s+15s\s", printed)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        pytest.param(15, "15s", id="seconds"),
        pytest.param(60, "1m0s", id="whole minutes still show seconds"),
        pytest.param(90, "1m30s", id="minutes and seconds"),
        pytest.param(0.5, "500ms", id="sub-second"),
    ],
)
def test_format_duration_matches_go(seconds: float, expected: str) -> None:
    # Go's time.Duration.String() renders 60s as "1m0s", not "1m". `make config`
    # output is compared between the two services by eye often enough to matter.
    assert format_duration(timedelta(seconds=seconds)) == expected


@pytest.mark.parametrize(
    ("text", "expected_seconds"),
    [
        pytest.param("15s", 15, id="seconds"),
        pytest.param("1m30s", 90, id="compound"),
        pytest.param("500ms", 0.5, id="milliseconds"),
        pytest.param("2h", 7200, id="hours"),
    ],
)
def test_go_style_durations_are_parsed(
    text: str, expected_seconds: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Both services read the same config.yaml, so Python must accept the
    # duration syntax Go writes.
    monkeypatch.setenv("{@ env_prefix @}_SERVER__READ_TIMEOUT", text)

    assert load(files=()).server.read_timeout == timedelta(seconds=expected_seconds)


def test_split_listeners() -> None:
    config = Config()
    assert config.split_listeners()

    # Collapsing onto one listener must remain expressible.
    config.server.admin_port = config.server.port
    assert not config.split_listeners()
