"""Tests for the version resolving and install scripts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import find_minimum_version as finder
import install_test_requirements as install_module
from packaging.version import Version
import pytest
import resolve_versions
import run_integration_tests as runner


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
def test_python_version_follows_homeassistant(
    homeassistant: str, expected: str
) -> None:
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
    assert install_module.release_date(Version("2025.11.0")) == "2025-11-05T19:46:00Z"


def test_named_packages(tmp_path: Path) -> None:
    """Comments, options and unparsable lines are skipped."""
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "# Integration\npypura==4.0.1\nical  # calendar\n-r other.txt\n\n"
    )
    assert install_module.named_packages(requirements) == ["pypura", "ical"]


def install_with(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, results: list[int]
) -> tuple[bool, list[tuple[str, ...]]]:
    """Install with faked command results, returning the commands run."""
    commands: list[tuple[str, ...]] = []

    def fake_run(*command: str | Path) -> int:
        commands.append(tuple(map(str, command)))
        return results[len(commands) - 1]

    monkeypatch.setattr(install_module, "run", fake_run)
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("serialx\n")
    result = install_module.install(Version("2025.11.0"), requirements, "python")
    return result, commands


def test_install_limits_dependencies_to_release_date(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Dependencies stop at the release date, except for named packages."""
    result, commands = install_with(monkeypatch, tmp_path, [0])
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


def test_install_tries_prereleases_then_drops_the_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Each fallback is tried in turn, and failing them all is reported."""
    result, commands = install_with(monkeypatch, tmp_path, [1, 1, 1])
    assert not result
    assert "--prerelease" not in commands[0]
    assert "--exclude-newer" in commands[1] and "--prerelease" in commands[1]
    assert "--exclude-newer" not in commands[2]


def test_no_minimum_tests_stable_with_a_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A hacs.json without a version skips the minimum channel."""
    (tmp_path / "hacs.json").write_text('{"name": "Example"}')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["resolve_versions.py", ""])
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    resolve_versions.main()
    captured = capsys.readouterr()
    assert "::warning::No homeassistant version" in captured.err
    channels = [entry["channel"] for entry in json.loads(captured.out)["include"]]
    assert channels == ["stable", "beta"]


def test_requirements_come_from_manifests_and_their_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requirements of Home Assistant dependencies are followed recursively."""
    domain = tmp_path / "custom_components" / "example"
    domain.mkdir(parents=True)
    (domain / "manifest.json").write_text(
        '{"requirements": ["lib==1"], "dependencies": ["http", "http"],'
        ' "after_dependencies": ["unknown"]}'
    )
    (domain / "camera.py").write_text(
        "from homeassistant.components.camera import Camera\n"
    )
    components = tmp_path / "components"
    for name, manifest in (
        ("camera", '{"requirements": ["PyTurboJPEG==1"]}'),
        ("http", '{"requirements": ["aiohttp==3"], "dependencies": ["network"]}'),
        ("network", '{"requirements": ["ifaddr==1"]}'),
    ):
        (components / name).mkdir(parents=True)
        (components / name / "manifest.json").write_text(manifest)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        install_module.subprocess,
        "run",
        lambda *_, **__: SimpleNamespace(stdout=f"{components}\n"),
    )
    assert install_module.integration_requirements() == ["lib==1"]
    assert sorted(install_module.dependency_requirements("python")) == [
        "PyTurboJPEG==1",
        "aiohttp==3",
        "ifaddr==1",
    ]


@pytest.mark.parametrize(
    ("loads", "own_code", "expected"),
    [(True, 0, True), (True, 5, True), (True, 1, False), (False, 0, False)],
)
def test_tests_pass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    loads: bool,
    own_code: int,
    expected: bool,
) -> None:
    """Having no tests is fine, but both the load check and tests must pass."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "install_manifest_requirements", lambda *_: None)
    monkeypatch.setattr(runner, "integration_loads", lambda _: loads)
    monkeypatch.setattr(runner, "run", lambda *_, **__: own_code)
    assert runner.tests_pass(Version("2026.11.0"), "missing.txt", "python") is expected


def test_run_tests_false_only_checks_loading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Opting out skips the integration's own tests."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "install_manifest_requirements", lambda *_: None)
    monkeypatch.setattr(runner, "integration_loads", lambda _: True)
    monkeypatch.setattr(runner, "run", lambda *_, **__: pytest.fail("pytest ran"))
    assert runner.tests_pass(Version("2026.11.0"), "missing.txt", "python", False)


def test_imported_components_only_counts_real_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every import form counts, but comments, strings and bad syntax don't."""
    domain = tmp_path / "custom_components" / "example"
    domain.mkdir(parents=True)
    (domain / "a.py").write_text(
        """
# homeassistant.components.hue
\"\"\"See homeassistant.components.zha.\"\"\"
from homeassistant.components import dhcp, zeroconf as zc
from homeassistant.components.camera import Camera
from . import homeassistant
import homeassistant.components.http.view


def later():
    from homeassistant.components import bluetooth
"""
    )
    (domain / "broken.py").write_text("from homeassistant.components.mqtt import (\n")
    monkeypatch.chdir(tmp_path)
    assert install_module.imported_components() == {
        "bluetooth",
        "camera",
        "dhcp",
        "http",
        "zeroconf",
    }


def test_tests_run_in_a_new_venv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Installing Home Assistant must not replace the uv doing the install."""
    commands: list[tuple[str, ...]] = []
    tested: list[Path] = []

    def fake_run(*command: str | Path) -> int:
        commands.append(tuple(map(str, command)))
        return 0

    def fake_tests_pass(_: Version, __: str, python: Path, ___: bool) -> bool:
        tested.append(python)
        return True

    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(runner, "tests_pass", fake_tests_pass)
    assert runner.tests_pass_in_venv(Version("2026.11.0"), "r.txt", True, "3.14")
    assert commands[0][:4] == ("uv", "venv", "--python", "3.14")
    assert tested == [Path(commands[0][4], "bin", "python")]


RELEASES = ["2025.1.1", "2025.2.0", "2025.2.1", "2025.2.2", "2025.3.0", "2025.3.1"]


@pytest.mark.parametrize(
    ("passing", "broken", "expected", "tried", "skipped"),
    [
        pytest.param(
            "2025.1.0", "", None, "2025.1.0", "", id="minimum-passes-on-retest"
        ),
        pytest.param(
            "2025.3.0 2025.3.1",
            "",
            "2025.3.0",
            "2025.1.0 2025.2.0 2025.3.0 2025.2.1 2025.2.2",
            "",
            id="first-month-to-pass",
        ),
        pytest.param(
            "2025.2.2 2025.3.0 2025.3.1",
            "",
            "2025.2.2",
            "2025.1.0 2025.2.0 2025.3.0 2025.2.1 2025.2.2",
            "",
            id="patch-of-previous-month",
        ),
        pytest.param(
            "2025.1.1 2025.2.0",
            "",
            "2025.1.1",
            "2025.1.0 2025.2.0 2025.1.1",
            "",
            id="patch-of-minimum-month",
        ),
        pytest.param(
            "2025.3.1",
            "",
            "2025.3.1",
            "2025.1.0 2025.2.0 2025.3.0 2025.3.1",
            "",
            id="patch-of-latest-month",
        ),
        pytest.param(
            "",
            "",
            None,
            "2025.1.0 2025.2.0 2025.3.0 2025.3.1",
            "",
            id="nothing-passes",
        ),
        pytest.param(
            "2025.2.0",
            "2025.1.0 2025.1.1",
            "2025.2.0",
            "2025.1.0 2025.2.0 2025.1.1",
            "2025.1.0 2025.1.1",
            id="minimum-cannot-install",
        ),
        pytest.param(
            "2025.2.1 2025.3.0",
            "2025.2.0",
            "2025.2.1",
            "2025.1.0 2025.2.0 2025.3.0 2025.2.1",
            "2025.2.0",
            id="month-cannot-install-but-patch-can",
        ),
    ],
)
def test_find_minimum(
    monkeypatch: pytest.MonkeyPatch,
    passing: str,
    broken: str,
    expected: str | None,
    tried: str,
    skipped: str,
) -> None:
    """Months are tried first, then the patches of the month before the first pass."""
    attempts: list[str] = []

    def fake_passes(version: Version, *_: Any) -> bool:
        attempts.append(str(version))
        if str(version) in broken.split():
            raise runner.SetupFailed("failed")
        return str(version) in passing.split()

    monkeypatch.setattr(finder, "passes", fake_passes)
    found, not_tested = finder.find(
        Version("2025.1.0"), [Version(v) for v in RELEASES], "r.txt", True
    )
    assert found == (Version(expected) if expected else None)
    assert attempts == tried.split()
    assert not_tested == [Version(version) for version in skipped.split()]


def test_report_writes_step_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The action reads the result from the step outputs."""
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    finder.report(Version("2025.3.0"), [Version("2025.1.0"), Version("2025.2.0")])
    assert output.read_text() == (
        "minimum-version=2025.3.0\nskipped-versions=2025.1.0, 2025.2.0\n"
    )


def test_no_hacs_json_has_no_minimum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An integration outside of HACS has no declared minimum."""
    monkeypatch.chdir(tmp_path)
    assert resolve_versions.declared_minimum() is None


def test_hidden_directories_are_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only real integration directories count."""
    for name in ("example", ".example"):
        domain = tmp_path / "custom_components" / name
        domain.mkdir(parents=True)
        (domain / "manifest.json").write_text(f'{{"domain": "{name}"}}')
    monkeypatch.chdir(tmp_path)
    assert install_module.manifests() == [{"domain": "example"}]
