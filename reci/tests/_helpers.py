"""Shared builders for the behavioural suite: offline, no network, no GitHub."""

from __future__ import annotations

from reci.action_spec import ActionSpec, parse_action_spec
from reci.graph import RecipeGraph
from reci.recipe import parse_recipe_string


def mk_spec(
    ref: str, *, inputs: dict | None = None, outputs: list[str] | None = None
) -> ActionSpec:
    """An :class:`ActionSpec` from compact input/output declarations."""
    return parse_action_spec(
        ref,
        action_yml_data={
            "inputs": inputs or {},
            "outputs": {name: {} for name in outputs or []},
        },
    )


def mk_graph(recipe_yaml: str, specs: dict[str, ActionSpec] | None = None):
    return RecipeGraph.from_recipe(parse_recipe_string(recipe_yaml), specs or {})


def _find_actionlint() -> str | None:
    """The ``actionlint`` binary: on PATH, or next to the running interpreter."""
    import shutil
    import sys
    from pathlib import Path

    return shutil.which("actionlint") or shutil.which(
        "actionlint", path=str(Path(sys.executable).parent)
    )


def lint_workflow(workflow: dict) -> list[str]:
    """Lint a compiled workflow with actionlint; return its complaints.

    Skips the calling test when actionlint is not installed (``pip install
    actionlint-py``, part of the ``dev`` extra), so a bare checkout still runs.
    """
    import subprocess
    import tempfile
    from pathlib import Path

    import pytest

    from reci.yaml_gen import dump_workflow

    exe = _find_actionlint()
    if exe is None:
        pytest.skip("actionlint not installed (pip install actionlint-py)")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "workflow.yml"
        path.write_text(dump_workflow(workflow))
        proc = subprocess.run(
            [exe, "-no-color", str(path)], capture_output=True, text=True
        )
    return [] if proc.returncode == 0 else proc.stdout.strip().splitlines()


def assert_valid_workflow(workflow: dict) -> None:
    """Fail with actionlint's complaints if the compiled workflow is invalid."""
    problems = lint_workflow(workflow)
    assert not problems, "actionlint rejected the workflow:\n" + "\n".join(problems)
