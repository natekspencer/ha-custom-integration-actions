"""Print the lowest Home Assistant version newer than hacs.json that tests pass on.

Usage: find_minimum_version.py REQUIREMENTS_FILE RUN_TESTS

Retests the minimum first, in case its failure was transient. Then tries each
release up to the latest stable one, oldest first, each on the Python version it
requires. Prints nothing if the tests pass on the minimum or fail on all of the
newer releases.
"""

from __future__ import annotations

import sys

from packaging.version import Version
from resolve_versions import declared_minimum, python_version, releases
from run_integration_tests import tests_pass_in_venv


def passes(homeassistant: Version, requirements_file: str, run_tests: bool) -> bool:
    """Return whether the integration passes on a Home Assistant version.

    Exits if the version can't be set up: it is untested, so moving on to a newer
    version could choose a minimum that is higher than needed.
    """
    python = python_version(homeassistant)
    return tests_pass_in_venv(homeassistant, requirements_file, run_tests, python)


def main() -> None:
    """Print the lowest passing version, if any."""
    requirements_file = sys.argv[1]
    run_tests = sys.argv[2] == "true"
    minimum = declared_minimum()
    if minimum is None:
        return
    homeassistant = releases("homeassistant")
    stable = next(version for version in homeassistant if not version.is_prerelease)
    candidates = sorted(
        version
        for version in homeassistant
        if minimum < version <= stable and not version.is_prerelease
    )
    if passes(minimum, requirements_file, run_tests):
        return
    for version in candidates:
        if passes(version, requirements_file, run_tests):
            print(version)
            return


if __name__ == "__main__":
    main()
