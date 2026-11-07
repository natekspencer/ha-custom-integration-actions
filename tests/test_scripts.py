"""Tests for the version resolving and install scripts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import install_test_requirements as install_module
from packaging.version import Version
import pytest
import resolve_versions


def file(version_yanked: bool = False) -> dict[str, Any]:
    """Return a PyPI file entry."""
    return {"yanked": version_yanked}


PYPI: dict[str, dict[str, Any]] = {
    "homeassistant": {
        "releases": {
            "2025.11.0": [file()],
            "2026.10.0": [file()],
            "2026.11.0": [file()],
            "2026.11.1": [file(True)],
            "2026.12.0b1": [file()],
        }
    },
    "homeassistant/2025.11.0": {
        "info": {"requires_python": ">=3.13.2"},
        "urls": [
            {"upload_time_iso_8601": "2025-11-05T19:45:13Z"},
            {"upload_time_iso_8601": "2025-11-05T19:46:00Z"},
        ],
    },
    "homeassistant/2026.11.0": {"info": {"requires_python": ">=3.14.2"}},
    "homeassistant/2026.12.0b1": {"info": {"requires_python": ">=3.15.0"}},
    "pytest-homeassistant": {
        "releases": {"0.1.0": [file()], "2026.11.0": [file()]},
    },
    "pytest-homeassistant-custom-component": {
        "releases": {"0.13.294": [file()], "0.13.300": [file()]},
    },
    "pytest-homeassistant-custom-component/0.13.300": {
        "info": {"requires_dist": ["homeassistant==2025.12.0"]},
    },
    "pytest-homeassistant-custom-component/0.13.294": {
        "info": {"requires_dist": ["pytest", "homeassistant==2025.11.0"]},
    },
}


@pytest.fixture(autouse=True)
def fake_pypi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve PyPI responses from the table above."""
    monkeypatch.setattr(resolve_versions, "pypi", PYPI.__getitem__)
    monkeypatch.setattr(install_module, "pypi", PYPI.__getitem__)


@pytest.mark.parametrize(
    ("homeassistant", "expected"),
    [("2025.11.0", "3.13"), ("2026.11.0", "3.14"), ("2026.12.0b1", "3.15")],
)
def test_python_version_follows_homeassistant(homeassistant: str, expected: str) -> None:
    """Each release uses the Python it requires."""
    assert resolve_versions.python_version(Version(homeassistant)) == expected


def test_python_version_needs_a_lower_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    """A requirement without a minimum is an error, not a guess."""
    monkeypatch.setattr(
        resolve_versions, "pypi", lambda _: {"info": {"requires_python": "<4"}}
    )
    with pytest.raises(SystemExit, match="No minimum Python"):
        resolve_versions.python_version(Version("2026.11.0"))


def test_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The matrix pairs each channel with its own Python version."""
    (tmp_path / "hacs.json").write_text('{"homeassistant": "2025.11.0"}')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["resolve_versions.py", ""])
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    resolve_versions.main()
    captured = capsys.readouterr()
    row = "| minimum | 2025.11.0 | 3.13 |"
    assert row in captured.err
    assert row in summary.read_text()
    assert json.loads(captured.out)["include"] == [
        {
            "channel": "minimum",
            "homeassistant-version": "2025.11.0",
            "python-version": "3.13",
        },
        {
            "channel": "stable",
            "homeassistant-version": "2026.11.0",
            "python-version": "3.14",
        },
        {
            "channel": "beta",
            "homeassistant-version": "2026.12.0b1",
            "python-version": "3.15",
        },
    ]


@pytest.mark.parametrize(
    ("homeassistant", "expected"),
    [
        ("2026.11.0", "pytest-homeassistant==2026.11.0"),
        ("2026.12.0b1", "pytest-homeassistant==2026.11.0"),
        ("2025.11.0", "pytest-homeassistant-custom-component==0.13.294"),
    ],
)
def test_test_package(homeassistant: str, expected: str) -> None:
    """The newest test package not newer than the target is chosen."""
    assert install_module.test_package(Version(homeassistant)) == expected


def test_release_date_is_the_last_upload() -> None:
    """All of a release's files are published by the limit."""
    assert (
        install_module.release_date(Version("2025.11.0")) == "2025-11-05T19:46:00Z"
    )


def test_named_packages(tmp_path: Path) -> None:
    """Comments, options and unparsable lines are skipped."""
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "# Integration\npypura==4.0.1\nical  # calendar\n-r other.txt\n\n"
    )
    assert install_module.named_packages(requirements) == ["pypura", "ical"]


def install_with(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, results: list[bool]
) -> tuple[bool, list[tuple[str, ...]]]:
    """Install with faked command results, returning the commands run."""
    commands: list[tuple[str, ...]] = []

    def fake_run(*command: str | Path) -> bool:
        commands.append(tuple(map(str, command)))
        return results[len(commands) - 1]

    monkeypatch.setattr(install_module, "run", fake_run)
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("serialx\n")
    result = install_module.install(Version("2025.11.0"), requirements, ("--system",))
    return result, commands


def test_install_limits_dependencies_to_release_date(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Dependencies stop at the release date, except for named packages."""
    result, commands = install_with(monkeypatch, tmp_path, [True])
    assert result
    assert len(commands) == 1
    command = commands[0]
    assert command[command.index("--exclude-newer") + 1] == "2025-11-05T19:46:00Z"
    exempt = {
        command[index + 1]
        for index, argument in enumerate(command)
        if argument == "--exclude-newer-package"
    }
    assert exempt == {
        "homeassistant=false",
        "pytest-homeassistant-custom-component=false",
        "serialx=false",
    }


def test_install_drops_the_limit_when_unsatisfiable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A requirement needing something newer doesn't stop the install."""
    result, commands = install_with(monkeypatch, tmp_path, [False, True])
    assert result
    assert "--exclude-newer" in commands[0]
    assert "--exclude-newer" not in commands[1]
