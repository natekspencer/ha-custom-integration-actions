#!/usr/bin/env python3
"""Print the lowest Home Assistant version newer than hacs.json that tests pass on.

Usage: find_minimum_version.py REQUIREMENTS_FILE

Retests the minimum first, in case its failure was transient. Then tries each
release up to the latest stable one, oldest first, each on the Python version it
requires. Prints nothing if the tests pass on the minimum or fail on all of the
newer releases.
"""

from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from install_test_requirements import install, run
from packaging.version import Version
from resolve_versions import declared_minimum, python_version, releases


def tests_pass(homeassistant: Version, requirements_file: str) -> bool:
    """Return whether the tests pass on a Home Assistant version.

    Exits if the version can't be set up: it is untested, so moving on to a newer
    version could choose a minimum that is higher than needed.
    """
    print(f"Testing Home Assistant {homeassistant}", file=sys.stderr)
    with TemporaryDirectory() as tmp:
        venv = Path(tmp, "venv")
        python = venv / "bin" / "python"
        if not (
            run("uv", "venv", "--python", python_version(homeassistant), venv)
            and install(homeassistant, requirements_file, ("--python", python))
        ):
            raise SystemExit(f"Could not set up Home Assistant {homeassistant}")
        return run(python, "-m", "pytest")


def main() -> None:
    """Print the lowest passing version, if any."""
    requirements_file = sys.argv[1]
    minimum = declared_minimum()
    homeassistant = releases("homeassistant")
    stable = next(version for version in homeassistant if not version.is_prerelease)
    candidates = sorted(
        version
        for version in homeassistant
        if minimum < version <= stable and not version.is_prerelease
    )
    if tests_pass(minimum, requirements_file):
        return
    for version in candidates:
        if tests_pass(version, requirements_file):
            print(version)
            return


if __name__ == "__main__":
    main()
