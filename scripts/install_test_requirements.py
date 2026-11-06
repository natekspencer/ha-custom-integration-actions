#!/usr/bin/env python3
"""Install an integration's test requirements for a Home Assistant version.

Usage: install_test_requirements.py HOMEASSISTANT_VERSION REQUIREMENTS_FILE

The test package may lag behind Home Assistant, so the exact version is forced
with an override.

Home Assistant doesn't pin all of its transitive dependencies, so a fresh install
of an older release can pull in ones that it never ran with. To match what users
of that release have, dependencies are resolved as of its release date, except
for the packages the integration names itself. If that can't be satisfied, for
example because a requirement needs something newer, the date limit is dropped.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import Version
from resolve_versions import pypi, releases

# Home Assistant publishes this package itself, starting with 2026.11.0b4.
TEST_PACKAGE = "pytest-homeassistant"
# Covers older versions. Remove once no integration tests below 2026.11.
LEGACY_TEST_PACKAGE = "pytest-homeassistant-custom-component"


def homeassistant_pin(requires: list[str]) -> Version | None:
    """Return the exact Home Assistant version in a list of requirements, if any."""
    for requirement in map(Requirement, requires):
        if requirement.name == "homeassistant":
            for specifier in requirement.specifier:
                if specifier.operator == "==":
                    return Version(specifier.version)
    return None


def legacy_test_package(target: Version) -> str:
    """Return the newest legacy test package not newer than the target version."""
    for release in releases(LEGACY_TEST_PACKAGE):
        requires = pypi(f"{LEGACY_TEST_PACKAGE}/{release}")["info"]["requires_dist"]
        pin = homeassistant_pin(requires or [])
        if pin is not None and pin <= target:
            return f"{LEGACY_TEST_PACKAGE}=={release}"
    raise SystemExit(f"No test package found for Home Assistant {target}")


def test_package(target: Version) -> str:
    """Return the requirement of the test package to use for the target version."""
    for release in releases(TEST_PACKAGE):
        # Releases below 2026 are an unrelated earlier use of the package name.
        if release.major >= 2026 and release <= target:
            return f"{TEST_PACKAGE}=={release}"
    return legacy_test_package(target)


def release_date(homeassistant: Version) -> str:
    """Return when a Home Assistant release was published."""
    files = pypi(f"homeassistant/{homeassistant}")["urls"]
    return max(file["upload_time_iso_8601"] for file in files)


def named_packages(requirements_file: str | Path) -> list[str]:
    """Return the packages named in a requirements file."""
    names = []
    for line in Path(requirements_file).read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        try:
            names.append(Requirement(line).name)
        except InvalidRequirement:
            print(f"Ignoring requirement: {line}", file=sys.stderr)
    return names


def run(*command: str | Path) -> bool:
    """Run a command, keeping stdout free for script results."""
    result = subprocess.run(command, check=False, stdout=sys.stderr)
    return result.returncode == 0


def install(
    homeassistant: Version,
    requirements_file: str | Path,
    target: Sequence[str | Path],
) -> bool:
    """Install the test requirements into the target, returning whether it worked."""
    package = test_package(homeassistant)
    with TemporaryDirectory() as tmp:
        overrides = Path(tmp, "overrides.txt")
        overrides.write_text(f"homeassistant=={homeassistant}\n")
        command = (
            *("uv", "pip", "install", *target),
            *("--requirement", requirements_file),
            *(package, "--override", overrides),
        )
        exempt = [
            "homeassistant",
            package.partition("==")[0],
            *named_packages(requirements_file),
        ]
        limit = ("--exclude-newer", release_date(homeassistant))
        for name in exempt:
            limit += ("--exclude-newer-package", f"{name}=false")
        if run(*command, *limit):
            return True
        print(
            f"::warning::Installing without the {homeassistant} release date limit",
            file=sys.stderr,
        )
        return run(*command)


def main() -> None:
    """Install into the active Python."""
    homeassistant, requirements_file = sys.argv[1:3]
    if not install(Version(homeassistant), requirements_file, ("--system",)):
        raise SystemExit(f"Could not set up Home Assistant {homeassistant}")


if __name__ == "__main__":
    main()
