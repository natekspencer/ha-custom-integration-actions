"""Test an integration on a Home Assistant version in the active Python.

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


def setup_failed(homeassistant: Version) -> SystemExit:
    """Return the error for a version that can't be tested."""
    return SystemExit(
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


def tests_pass(
    homeassistant: Version,
    requirements_file: str,
    python: str | Path,
    run_tests: bool = True,
) -> bool:
    """Return whether the integration passes on a Home Assistant version.

    Exits if the version can't be set up, as that says nothing about the
    integration.
    """
    log(f"Testing Home Assistant {homeassistant}")
    install_manifest_requirements(homeassistant, python)
    loads = integration_loads(python)
    if not run_tests:
        return loads
    if Path(requirements_file).exists() and not install(
        homeassistant, requirements_file, python
    ):
        raise setup_failed(homeassistant)
    # Run these even if it doesn't load, as they can show more of what is wrong
    return own_tests_pass(python) and loads


def main() -> None:
    """Test the integration, exiting with an error if it fails."""
    homeassistant, requirements_file, run_tests = sys.argv[1:4]
    if not tests_pass(
        Version(homeassistant), requirements_file, sys.executable, run_tests == "true"
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
