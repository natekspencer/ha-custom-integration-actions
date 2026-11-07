"""Find the lowest Home Assistant version newer than hacs.json that tests pass on.

Usage: find_minimum_version.py REQUIREMENTS_FILE RUN_TESTS

Retests the minimum first, in case its failure was transient. Then tries the first
release of each month up to the latest stable one, oldest first, as that is where
breaking changes land. When one passes, steps back from the latest patch release of
the month before it, as a patch may have fixed the failure, and stops at the first
that fails. Each runs on the Python version it requires. Reports no version if the tests pass on the minimum or
fail on all of the newer releases.

A version that can't be installed is skipped and reported, as old test packages
can pin something that is no longer on PyPI. Stopping there would leave a minimum
that can never be tested. The result may be higher than needed if a version only
failed to install temporarily, but it is proposed in a PR for review.

Also reports the lowest version the integration loaded on, when that is below the
result, as its tests may just be behind. Only the first release of most months is
tried, so this is accurate to the month.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import sys

from packaging.version import Version
from resolve_versions import declared_minimum, python_version, releases
from run_integration_tests import Outcome, SetupFailed, test_version_in_venv


@dataclass
class Search:
    """The result of a search for a new minimum."""

    version: Version | None = None
    skipped: list[Version] = field(default_factory=list)
    loaded_on: list[Version] = field(default_factory=list)

    @property
    def loads_from(self) -> Version | None:
        """Return the lowest version it loaded on, if below the new minimum."""
        lowest = min(self.loaded_on, default=None)
        if lowest is None or self.version is None or lowest >= self.version:
            return None
        return lowest


def run(homeassistant: Version, requirements_file: str, run_tests: bool) -> Outcome:
    """Return how the integration does on a Home Assistant version."""
    python = python_version(homeassistant)
    return test_version_in_venv(homeassistant, requirements_file, run_tests, python)


def report(search: Search) -> None:
    """Write the result to the step outputs, or stdout outside of GitHub Actions."""
    lines = (
        f"minimum-version={search.version or ''}\n"
        f"skipped-versions={', '.join(map(str, search.skipped))}\n"
        f"loads-from={search.loads_from or ''}\n"
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
) -> Search:
    """Return the lowest version passing along with those after it, if not the minimum."""
    search = Search()

    def check(version: Version) -> bool:
        """Return whether a version passes, skipping it if it can't be installed."""
        try:
            outcome = run(version, requirements_file, run_tests)
        except SetupFailed:
            print(f"::warning::Skipping Home Assistant {version}", file=sys.stderr)
            search.skipped.append(version)
            return False
        if outcome.loads:
            search.loaded_on.append(version)
        return outcome.passed

    def step_back(patches: list[Version], passing: Version | None) -> Version | None:
        """Return the lowest version that passes along with all those after it."""
        for version in reversed(patches):
            if not check(version):
                break
            passing = version
        return passing

    groups = months([minimum, *candidates])
    for index, group in enumerate(groups):
        if not check(group[0]):
            continue
        if index > 0:
            search.version = step_back(groups[index - 1][1:], group[0])
        return search
    # No month started out passing, so only the latest month's patches are left
    search.version = step_back(groups[-1][1:], None)
    return search


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
    report(find(minimum, candidates, requirements_file, run_tests))


if __name__ == "__main__":
    main()
