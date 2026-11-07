"""Test an integration on a Home Assistant version.

Usage: run_integration_tests.py HOMEASSISTANT_VERSION REQUIREMENTS_FILE RUN_TESTS

First checks that the integration loads with only the requirements in its
manifest. Then, unless RUN_TESTS is false, installs the requirements file, if there
is one, and runs the integration's own tests, if pytest finds any.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import NamedTuple

from install_test_requirements import (
    dependency_requirements,
    install,
    integration_requirements,
    run,
)
from packaging.version import Version

LOAD_CHECK = Path(__file__).parent.parent / "checks" / "test_integration_loads.py"
# pytest's exit code when it collects no tests.
NO_TESTS = 5


def log(message: str) -> None:
    """Print to the log, keeping stdout free for script results."""
    print(message, file=sys.stderr)


class Outcome(NamedTuple):
    """What happened on a Home Assistant version."""

    loads: bool
    own_tests_passed: bool

    @property
    def passed(self) -> bool:
        """Return whether everything passed."""
        return self.loads and self.own_tests_passed


class SetupFailed(SystemExit):
    """A Home Assistant version can't be installed, so it is untested."""


def setup_failed(homeassistant: Version) -> SetupFailed:
    """Return the error for a version that can't be tested."""
    return SetupFailed(
        f"::error::Could not install Home Assistant {homeassistant} and its test "
        "requirements. It is untested, see the install output above."
    )


def install_manifest_requirements(homeassistant: Version, python: str | Path) -> None:
    """Install what the integration's manifest and its dependencies declare."""
    with TemporaryDirectory() as tmp:
        requirements = Path(tmp, "requirements.txt")
        declared = integration_requirements()
        requirements.write_text("\n".join(declared) + "\n")
        if not install(homeassistant, requirements, python):
            raise setup_failed(homeassistant)
        if inherited := dependency_requirements(python):
            requirements.write_text("\n".join((*declared, *inherited)) + "\n")
            if not install(homeassistant, requirements, python):
                raise setup_failed(homeassistant)


def integration_loads(python: str | Path) -> bool:
    """Return whether the integration loads."""
    log("Checking that the integration loads")
    code = run(
        *(python, "-m", "pytest", LOAD_CHECK),
        *("--rootdir", Path.cwd(), "-c", os.devnull),
        *("-p", "no:cacheprovider", "-p", "no:respx"),
        *("-o", "asyncio_mode=auto"),
        env={**os.environ, "PYTHONPATH": str(Path.cwd())},
    )
    return code == 0


def own_tests_pass(python: str | Path) -> bool:
    """Return whether the integration's own tests pass, if it has any."""
    log("Running the integration's tests")
    code = run(
        *(python, "-m", "pytest"),
        # Home Assistant must install its httpx alias before respx is imported
        env={**os.environ, "PYTEST_ADDOPTS": "-p no:respx"},
    )
    if code == NO_TESTS:
        log("The integration has no tests of its own")
        return True
    return code == 0


def test_version(
    homeassistant: Version,
    requirements_file: str,
    python: str | Path,
    run_tests: bool = True,
) -> Outcome:
    """Return how the integration does on a Home Assistant version.

    Exits if the version can't be set up, as that says nothing about the
    integration.
    """
    log(f"Testing Home Assistant {homeassistant}")
    install_manifest_requirements(homeassistant, python)
    loads = integration_loads(python)
    if not run_tests:
        return Outcome(loads, True)
    if Path(requirements_file).exists() and not install(
        homeassistant, requirements_file, python
    ):
        raise setup_failed(homeassistant)
    # Run these even if it doesn't load, as they can show more of what is wrong
    return Outcome(loads, own_tests_pass(python))


def test_version_in_venv(
    homeassistant: Version,
    requirements_file: str,
    run_tests: bool,
    python_request: str,
) -> Outcome:
    """Return how the integration does in a new virtual environment.

    Home Assistant pins uv as a dependency, so installing it next to the uv running
    the install would replace that with a version that may not support our options.
    """
    with TemporaryDirectory() as tmp:
        venv = Path(tmp, "venv")
        if run("uv", "venv", "--python", python_request, venv) != 0:
            raise setup_failed(homeassistant)
        python = venv / "bin" / "python"
        return test_version(homeassistant, requirements_file, python, run_tests)


def main() -> None:
    """Test the integration, exiting with an error if it fails."""
    homeassistant, requirements_file, run_tests = sys.argv[1:4]
    outcome = test_version_in_venv(
        Version(homeassistant), requirements_file, run_tests == "true", sys.executable
    )
    if not outcome.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
