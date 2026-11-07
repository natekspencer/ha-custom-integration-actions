"""Find the lowest Home Assistant version newer than hacs.json that tests pass on.

Usage: find_minimum_version.py REQUIREMENTS_FILE RUN_TESTS

Retests the minimum first, in case its failure was transient. Then tries the first
release of each month up to the latest stable one, oldest first, as that is where
breaking changes land. When one passes, steps back through the patch releases of
the month before it, as one of those may have fixed the failure. Each runs on the
Python version it requires. Reports no version if the tests pass on the minimum or
fail on all of the newer releases.

A version that can't be installed is skipped and reported, as old test packages
can pin something that is no longer on PyPI. Stopping there would leave a minimum
that can never be tested. The result may be higher than needed if a version only
failed to install temporarily, but it is proposed in a PR for review.
"""

from __future__ import annotations

import os
import sys

from packaging.version import Version
from resolve_versions import declared_minimum, python_version, releases
from run_integration_tests import SetupFailed, tests_pass_in_venv


def passes(homeassistant: Version, requirements_file: str, run_tests: bool) -> bool:
    """Return whether the integration passes on a Home Assistant version."""
    python = python_version(homeassistant)
    return tests_pass_in_venv(homeassistant, requirements_file, run_tests, python)


def report(version: Version | None, skipped: list[Version]) -> None:
    """Write the result to the step outputs, or stdout outside of GitHub Actions."""
    lines = (
        f"minimum-version={version or ''}\n"
        f"skipped-versions={', '.join(map(str, skipped))}\n"
    )
    if path := os.environ.get("GITHUB_OUTPUT"):
        with open(path, "a") as file:
            file.write(lines)
    else:
        print(lines, end="")


def months(versions: list[Version]) -> list[list[Version]]:
    """Group sorted versions by the month they were released in."""
    groups: dict[tuple[int, int], list[Version]] = {}
    for version in versions:
        groups.setdefault((version.major, version.minor), []).append(version)
    return list(groups.values())


def find(
    minimum: Version, candidates: list[Version], requirements_file: str, run_tests: bool
) -> tuple[Version | None, list[Version]]:
    """Return the lowest passing version, if it isn't the minimum, and those skipped."""
    skipped: list[Version] = []

    def check(version: Version) -> bool:
        """Return whether a version passes, skipping it if it can't be installed."""
        try:
            return passes(version, requirements_file, run_tests)
        except SetupFailed:
            print(f"::warning::Skipping Home Assistant {version}", file=sys.stderr)
            skipped.append(version)
            return False

    groups = months([minimum, *candidates])
    for index, group in enumerate(groups):
        if not check(group[0]):
            continue
        if index == 0:
            return None, skipped
        passing = next(filter(check, groups[index - 1][1:]), group[0])
        return passing, skipped
    # No month started out passing, so only the latest month's patches are left
    return next(filter(check, groups[-1][1:]), None), skipped


def main() -> None:
    """Report the lowest passing version, if any."""
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
    report(*find(minimum, candidates, requirements_file, run_tests))


if __name__ == "__main__":
    main()
