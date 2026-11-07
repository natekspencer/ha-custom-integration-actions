"""Install what an integration needs on a Home Assistant version.

The test package may lag behind Home Assistant, so the exact version is forced
with an override.

Home Assistant doesn't pin all of its transitive dependencies, so a fresh install
of an older release can pull in ones that it never ran with. To match what users
of that release have, dependencies are resolved as of its release date, except
for the packages the integration names itself. If that can't be satisfied, for
example because a requirement needs something newer, the date limit is dropped.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import Version
from resolve_versions import pypi, releases

# Home Assistant publishes this package itself, starting with 2026.11.0b4.
TEST_PACKAGE = "pytest-homeassistant"
# Covers older versions. Remove once no integration tests below 2026.11.
LEGACY_TEST_PACKAGE = "pytest-homeassistant-custom-component"
COMPONENTS_PACKAGE = ["homeassistant", "components"]


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


def manifests() -> list[dict[str, Any]]:
    """Return the manifests of the integrations in the repository."""
    return [
        json.loads(path.read_text())
        for path in sorted(Path("custom_components").glob("*/manifest.json"))
        if not path.parent.name.startswith(".")
    ]


def integration_requirements() -> list[str]:
    """Return the requirements the integration's manifests declare."""
    return [
        requirement
        for manifest in manifests()
        for requirement in manifest.get("requirements", [])
    ]


def dependencies(manifest: dict[str, Any]) -> list[str]:
    """Return the integrations a manifest depends on."""
    return manifest.get("dependencies", []) + manifest.get("after_dependencies", [])


def component_of(module: str) -> str | None:
    """Return the Home Assistant integration a module belongs to, if any."""
    parts = module.split(".")
    return parts[2] if len(parts) > 2 and parts[:2] == COMPONENTS_PACKAGE else None


def imports_in(source: str) -> Iterator[str]:
    """Yield the modules imported by Python source, at any level of the code."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # The load check reports this
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            yield node.module
            # Each name might be a module, as in `from homeassistant.components import dhcp`
            yield from (f"{node.module}.{alias.name}" for alias in node.names)


def imported_components() -> set[str]:
    """Return the Home Assistant integrations the code imports from.

    An integration with a camera platform doesn't list camera as a dependency, as
    Home Assistant sets it up when it loads the platform.
    """
    return {
        domain
        for path in Path("custom_components").rglob("*.py")
        for module in imports_in(path.read_text())
        if (domain := component_of(module))
    }


def dependency_requirements(python: str | Path) -> list[str]:
    """Return the requirements of the Home Assistant integrations depended on.

    Home Assistant installs these at runtime, so a fresh install doesn't have them.
    """
    result = subprocess.run(
        (python, "-c", "import homeassistant.components as c; print(c.__path__[0])"),
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    components = Path(result.stdout.strip())
    requirements: list[str] = []
    seen: set[str] = set()
    pending = [
        *imported_components(),
        *(domain for manifest in manifests() for domain in dependencies(manifest)),
    ]
    while pending:
        domain = pending.pop()
        path = components / domain / "manifest.json"
        if domain in seen or not path.exists():
            continue
        seen.add(domain)
        manifest = json.loads(path.read_text())
        requirements += manifest.get("requirements", [])
        pending += dependencies(manifest)
    return list(dict.fromkeys(requirements))


def run(*command: str | Path, env: Mapping[str, str] | None = None) -> int:
    """Run a command, keeping stdout free for script results."""
    return subprocess.run(command, check=False, env=env, stdout=sys.stderr).returncode


def install(
    homeassistant: Version, requirements_file: str | Path, python: str | Path
) -> bool:
    """Install requirements into a Python, returning whether it worked."""
    package = test_package(homeassistant)
    with TemporaryDirectory() as tmp:
        overrides = Path(tmp, "overrides.txt")
        overrides.write_text(f"homeassistant=={homeassistant}\n")
        command = (
            *("uv", "pip", "install", "--python", python),
            *("--requirement", requirements_file),
            *(package, "--override", overrides),
        )
        exempt = [
            "homeassistant",
            package.partition("==")[0],
            *named_packages(requirements_file),
        ]
        limit: tuple[str, ...] = ("--exclude-newer", release_date(homeassistant))
        for name in exempt:
            limit += ("--exclude-newer-package", f"{name}=false")
        # Some releases pin a pre-release of a dependency
        attempts = (limit, (*limit, "--prerelease", "allow"), ())
        for attempt in attempts:
            if not attempt:
                print(
                    f"::warning::Installing without the {homeassistant} release date limit",
                    file=sys.stderr,
                )
            if run(*command, *attempt) == 0:
                return True
        return False
