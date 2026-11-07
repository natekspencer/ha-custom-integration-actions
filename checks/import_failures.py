"""Decide what a failed import of an integration's module means."""

from __future__ import annotations

from importlib.util import find_spec

OWN_PACKAGES = ("custom_components", "homeassistant")


def is_real_failure(missing: str) -> bool:
    """Return whether a missing module means more than an undeclared requirement.

    Part of Home Assistant, the integration or an installed package being missing is
    a real failure. A namespace package is shared by separate distributions, so a
    missing part of one is just another package that isn't installed.
    """
    package = missing.partition(".")[0]
    if not package or package in OWN_PACKAGES:
        return True
    spec = find_spec(package)
    return spec is not None and spec.origin is not None
