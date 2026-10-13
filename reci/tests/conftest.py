"""Fixtures for the behavioural suite."""

import pytest

from reci.action_spec import ActionSpec
from reci.tests._helpers import mk_spec


@pytest.fixture
def pipeline_recipe_yaml() -> str:
    """A representative three-step, single-job pipeline (checkout -> build -> test)."""
    return """\
name: CI
on:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: acme/ci/actions/build@v1
      - uses: acme/ci/actions/run-tests@v1
        with:
          verbose: "true"
"""


@pytest.fixture
def pipeline_specs() -> dict[str, ActionSpec]:
    return {
        "actions/checkout@v4": mk_spec("actions/checkout@v4"),
        "acme/ci/actions/build@v1": mk_spec(
            "acme/ci/actions/build@v1",
            inputs={"python_version": {"required": True}},
            outputs=["wheel_path"],
        ),
        "acme/ci/actions/run-tests@v1": mk_spec(
            "acme/ci/actions/run-tests@v1",
            inputs={
                "wheel_path": {"required": True},
                "verbose": {"default": "false"},
                "root_dir": {"default": "."},
            },
        ),
    }
