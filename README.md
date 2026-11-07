# Home Assistant custom integration actions

Shared GitHub Actions for testing Home Assistant custom integrations against the
versions they claim to support.

## What it does

The `compatibility` workflow checks that an integration loads, runs its tests if it
has any, and does both on:

| Channel   | Home Assistant version                              |
| --------- | --------------------------------------------------- |
| `minimum` | The `homeassistant` version declared in `hacs.json`, if any |
| `stable`  | The latest release                                  |
| `beta`    | The latest pre-release, while newer than stable     |
| `manual`  | The `homeassistant-version` input, if given         |

When the tests fail on the minimum but pass on stable, it finds the lowest version
they pass on and opens a PR to update `hacs.json`. It tries the first release of each
month until one passes, then steps back from the latest patch of the month before it. On scheduled runs, a failure on
stable or a beta opens one issue per monthly release.

Review bump PRs before merging, as HACS stops offering updates to users below the
minimum. The new minimum is the lowest version everything passes on, which can be held
back by the tests alone. If the integration loads on an earlier version, the PR says
so, and fixing the tests may be better than raising the minimum.

## Usage

Add a `compatibility` job to the integration's validation workflow, here alongside
hassfest and HACS in `.github/workflows/validate.yml`:

```yaml
name: Validate repo

on:
  push:
    branches:
      - main
  pull_request:
  schedule:
    # Daily, to catch new Home Assistant releases and betas
    - cron: "0 0 * * *"
  workflow_dispatch:
    inputs:
      homeassistant-version:
        description: Also test this Home Assistant version (e.g. 2026.8.0)
        required: false
        type: string

permissions:
  contents: read

concurrency:
  group: ${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  hassfest:
    name: Validate with hassfest
    runs-on: "ubuntu-latest"
    steps:
      - uses: "actions/checkout@v7"
        with:
          persist-credentials: false
      - uses: "home-assistant/actions/hassfest@master"
  hacs:
    name: Validate with HACS
    runs-on: "ubuntu-latest"
    steps:
      - uses: "hacs/action@main"
        with:
          category: "integration"
  compatibility:
    name: Compatibility
    permissions:
      actions: read
      contents: write
      issues: write
      pull-requests: write
    uses: natekspencer/ha-custom-integration-actions/.github/workflows/compatibility.yml@v0
    with:
      homeassistant-version: ${{ inputs.homeassistant-version }}
    secrets:
      BUMP_PR_TOKEN: ${{ secrets.BUMP_PR_TOKEN }}
```

The job needs its own `permissions`, as it opens bump PRs and issues.

### Requirements

| File                                      | Needed                                                                  |
| ----------------------------------------- | ----------------------------------------------------------------------- |
| `custom_components/<domain>/manifest.json` | Yes                                                                     |
| `hacs.json`                               | Without a `homeassistant` version, the minimum is skipped with a warning |
| `requirements_test.txt`                   | Only for packages the integration's own tests need                      |
| Tests                                     | No, but see below. pytest finds them using the repository's configuration |

An integration with no tests still gets the standard check. The integration must be in
`custom_components/<domain>/`, so `content_in_root` in `hacs.json` isn't supported.

## The standard check

Every run first imports each module of the integration, with only what its manifest
provides: its `requirements`, and those of the Home Assistant integrations it lists
in `dependencies` and `after_dependencies` or imports from. No setup is needed.

This fails on Home Assistant APIs that were removed. A package missing from the
manifest is a warning on `manifest.json`, and that module is skipped. It isn't a
failure because Home Assistant's container images include the requirements of its
built-in integrations, so the integration often still works there, and raising the
minimum version wouldn't fix it. `requirements_test.txt` isn't installed yet, so it
can't hide a missing requirement.

This shows that the integration loads, not that it works, so it doesn't replace real
tests.

## Adding tests

Add tests, `requirements_test.txt` for anything they need, and this to `pyproject.toml`.
Without `asyncio_mode = "auto"`, async fixtures fail:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
pythonpath = ["."]
testpaths = ["tests"]
```

From Home Assistant 2026.11 the test package is `pytest-homeassistant`, so tests that
run on older versions too need to import from either one:

```python
try:
    from pytest_homeassistant.common import MockConfigEntry
except ImportError:
    from pytest_homeassistant_custom_component.common import MockConfigEntry
```

The workflow runs pytest with `-p no:respx`, so that Home Assistant can install its
httpx alias first. To run the tests locally on recent versions, add
`addopts = "-p no:respx"` too.

### Inputs

| Input                   | Default                 | Description                             |
| ----------------------- | ----------------------- | --------------------------------------- |
| `homeassistant-version` |                         | Also test this Home Assistant version   |
| `requirements-file`     | `requirements_test.txt` | Requirements file for the integration's tests, used if it exists |
| `run-tests`             | `true`                  | Run the integration's own tests as well as the standard check |

Own tests run by default, as other CI usually only covers one Home Assistant version.
With `run-tests: false`, bump PRs are based only on whether the integration loads.

### Secrets

| Secret          | Description                                                                                                             |
| --------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `BUMP_PR_TOKEN` | Optional token for bump PRs. Without it the PR is opened with `GITHUB_TOKEN`, and GitHub won't start its workflows. |

## Resolved versions

The versions and Python each channel resolved to appear at the top of the run's
summary page, and in the log of the `Resolve Home Assistant versions` job.

## Python versions

There is no Python version to configure. Each Home Assistant version runs on the
Python it requires, read from its `requires_python` on PyPI. When Home Assistant
moves to a new Python, stable and beta follow it, while a minimum that is still on
an older release keeps testing on the older Python.

## Dependencies of older releases

Home Assistant doesn't pin all of its transitive dependencies, so a fresh install of
an older release can pull in versions it never ran with. Dependencies are therefore
resolved as of the release date of the version under test. Home Assistant, the test
package and everything named in the requirements file are exempt. If that can't be
satisfied, the install tries allowing pre-releases, then warns and drops the date limit.

A release that still can't be installed fails with an error, as it is untested. This
happens when a very old test package pins something no longer on PyPI. When that is
the minimum, the search for a new one skips any version it can't install and lists
them in the bump PR, so check that list before merging.

## Releasing

This is pre-1.0, so inputs and behavior may still change. Integrations use the moving
`v0` tag, and the workflow calls the actions in this repository at `@v0`, so a change
reaches integrations once that tag moves. After merging, tag the release and move it:

```sh
git tag v0.2.0
git tag --force v0
git push origin v0.2.0
git push --force origin v0
```

When the interface is stable, release `v1.0.0` with a moving `v1` tag, and update
`compatibility.yml` and the integrations to `@v1`.
