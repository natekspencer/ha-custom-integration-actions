#!/usr/bin/env python3
"""Print the GitHub Actions matrix of Home Assistant versions to test against.

Channels:
  minimum  the version declared in hacs.json
  stable   the latest Home Assistant release
  beta     the latest pre-release, while it is newer than stable
  manual   the version passed as an argument, if any

Each entry names the Python version that Home Assistant release requires, so a
new Python requirement in Home Assistant needs no change here or in any
integration, and older releases keep testing on the Python they ran on.
"""

from __future__ import annotations

from functools import cache
from http.client import HTTPException
import json
from pathlib import Path
import sys
from time import sleep
from typing import Any
from urllib.error import HTTPError
from urllib.request import urlopen

from packaging.specifiers import SpecifierSet
from packaging.version import Version

# Seconds to wait before each retry of a failed PyPI request.
RETRY_DELAYS = (2, 5, 15)


def fetch_json(url: str) -> dict[str, Any]:
    """Return the JSON at a URL."""
    with urlopen(url, timeout=30) as response:
        return json.load(response)


@cache
def pypi(path: str) -> dict[str, Any]:
    """Return the PyPI JSON for a package or a package release.

    Retries network errors and server errors, but not a missing package.
    """
    url = f"https://pypi.org/pypi/{path}/json"
    for delay in RETRY_DELAYS:
        try:
            return fetch_json(url)
        except (OSError, HTTPException) as err:
            if isinstance(err, HTTPError) and err.code < 500 and err.code != 429:
                raise
            print(f"Retrying {url} in {delay}s: {err}", file=sys.stderr)
            sleep(delay)
    return fetch_json(url)


def releases(package: str) -> list[Version]:
    """Return the non-yanked releases of a package, newest first."""
    return sorted(
        (
            Version(version)
            for version, files in pypi(package)["releases"].items()
            if files and not all(file["yanked"] for file in files)
        ),
        reverse=True,
    )


def declared_minimum() -> Version:
    """Return the minimum Home Assistant version declared in hacs.json."""
    return Version(json.loads(Path("hacs.json").read_text())["homeassistant"])


def python_version(homeassistant: Version) -> str:
    """Return the major.minor Python version a Home Assistant release requires."""
    requires_python = pypi(f"homeassistant/{homeassistant}")["info"]["requires_python"]
    lower_bounds = [
        Version(specifier.version)
        for specifier in SpecifierSet(requires_python)
        if specifier.operator in (">=", "~=", "==")
    ]
    if not lower_bounds:
        raise SystemExit(
            f"No minimum Python in Home Assistant {homeassistant}: {requires_python}"
        )
    minimum = max(lower_bounds)
    return f"{minimum.major}.{minimum.minor}"


def main() -> None:
    """Print the matrix as JSON."""
    homeassistant = releases("homeassistant")
    stable = next(version for version in homeassistant if not version.is_prerelease)
    channels = {
        "minimum": declared_minimum(),
        "stable": stable,
    }
    if homeassistant[0] > stable:
        channels["beta"] = homeassistant[0]
    if len(sys.argv) > 1 and sys.argv[1]:
        channels["manual"] = Version(sys.argv[1])

    include = [
        {
            "channel": channel,
            "homeassistant-version": str(version),
            "python-version": python_version(version),
        }
        for channel, version in channels.items()
    ]
    print(json.dumps({"include": include}))


if __name__ == "__main__":
    main()
