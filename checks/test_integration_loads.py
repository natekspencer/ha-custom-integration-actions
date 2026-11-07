"""Standard check that an integration loads on a Home Assistant version.

Runs from the integration's repository, with only the requirements its manifest
declares, so a dependency that is only installed for tests can't hide a missing
requirement. This proves the integration loads, not that it works.

A missing package is a warning, not a failure. Home Assistant's container images
include the requirements of its built-in integrations, so the integration usually
still works there, and raising the minimum version wouldn't fix it.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from import_failures import is_real_failure
import pytest

from homeassistant import loader
from homeassistant.core import HomeAssistant

COMPONENTS = Path.cwd() / "custom_components"
DOMAINS = sorted(
    path.parent.name
    for path in COMPONENTS.glob("*/manifest.json")
    if not path.parent.name.startswith(".")
)
MODULES = sorted(
    ".".join(path.relative_to(COMPONENTS.parent).with_suffix("").parts).removesuffix(
        ".__init__"
    )
    for domain in DOMAINS
    for path in (COMPONENTS / domain).rglob("*.py")
)

reported: set[str] = set()


def test_integration_exists() -> None:
    """Fail rather than pass with nothing to check."""
    assert DOMAINS, "No custom_components/*/manifest.json found"


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module: str, capsys: pytest.CaptureFixture[str]) -> None:
    """Import a module, warning about a package the manifest doesn't provide."""
    try:
        import_module(module)
    except ModuleNotFoundError as err:
        missing = err.name or ""
        if is_real_failure(missing):
            raise
        message = (
            f"{module} needs {missing}, which the manifest requirements don't provide"
        )
        if missing not in reported:
            reported.add(missing)
            manifest = Path(*module.split(".")[:2], "manifest.json")
            with capsys.disabled():
                print(f"\n::warning file={manifest}::{message}")
        pytest.skip(message)


@pytest.mark.parametrize("domain", DOMAINS)
async def test_manifest_loads(
    hass: HomeAssistant, enable_custom_integrations: None, domain: str
) -> None:
    """Home Assistant can read the integration."""
    assert await loader.async_get_integration(hass, domain)
