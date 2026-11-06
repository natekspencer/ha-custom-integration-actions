# Home Assistant custom integration actions

Shared GitHub Actions for testing Home Assistant custom integrations against the
versions they claim to support.

## What it does

The `compatibility` workflow tests an integration on:

| Channel   | Home Assistant version                              |
| --------- | --------------------------------------------------- |
| `minimum` | The `homeassistant` version declared in `hacs.json` |
| `stable`  | The latest release                                  |
| `beta`    | The latest pre-release, while newer than stable     |
| `manual`  | The `homeassistant-version` input, if given         |

When the tests fail on the minimum but pass on stable, it finds the lowest version
they pass on and opens a PR to update `hacs.json`. On scheduled runs, a failure on
stable or a beta opens one issue per monthly release.

## Usage

Add `.github/workflows/tests.yml` to the integration:

```yaml
name: Tests

on:
  push:
    branches:
      - main
  pull_request:
  schedule:
    # Daily, to catch new Home Assistant releases and betas
    - cron: "17 6 * * *"
  workflow_dispatch:
    inputs:
      homeassistant-version:
        description: Also test this Home Assistant version (e.g. 2026.8.0)
        required: false
        type: string

permissions: {}

concurrency:
  group: ${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
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

The integration needs a `hacs.json` with a `homeassistant` version, a requirements
file and pytest configuration.

### Inputs

| Input                   | Default                 | Description                             |
| ----------------------- | ----------------------- | --------------------------------------- |
| `homeassistant-version` |                         | Also test this Home Assistant version   |
| `requirements-file`     | `requirements_test.txt` | Requirements file of the integration    |

### Secrets

| Secret          | Description                                                                                                             |
| --------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `BUMP_PR_TOKEN` | Optional token for bump PRs. Without it the PR is opened with `GITHUB_TOKEN`, and GitHub won't start its workflows. |

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
satisfied, the install warns and tries again without the date limit.

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
