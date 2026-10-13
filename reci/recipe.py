"""Recipe model — declarative CI pipeline description.

A recipe is a YAML file that looks like a GitHub Actions workflow but with
reci extensions: ``${{ config.* }}`` references, ``bind:`` mappings for
input renaming, and ``outputs:`` annotations on ``run:`` steps.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from ruamel.yaml.scalarbool import ScalarBoolean

from reci.action_spec import normalize_name
from reci.yaml_gen import load_yaml


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepSpec:
    """One step inside a job."""

    id: str
    uses: str | None = None
    run: str | None = None
    with_: dict[str, str] = field(default_factory=dict)
    if_: str | None = None
    name: str | None = None
    outputs: list[str] = field(default_factory=list)
    bind: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class JobSpec:
    """One job inside a recipe."""

    id: str
    steps: list[StepSpec] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)
    if_: str | None = None
    runs_on: str = "ubuntu-latest"
    strategy: dict | None = None
    permissions: dict | None = None
    continue_on_error: bool | str = False  # a bool, or an expression string
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Recipe:
    """A complete reci recipe."""

    name: str
    on: Any  # str | list | dict — GitHub Actions trigger spec
    jobs: dict[str, JobSpec] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    defaults: dict | None = None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class RecipeParseError(Exception):
    """Raised when a recipe YAML is structurally invalid."""


def _auto_step_id(step_data: dict, *, index: int, job_id: str) -> str:
    """Derive a step ID when the recipe doesn't provide one.

    Uses the action's last path segment (normalized) or ``step_{index}``.
    """
    if uses := step_data.get("uses"):
        last = uses.split("@", 1)[0].rsplit("/", 1)[-1]
        return normalize_name(last)
    return f"step_{index}"


def _scalar_to_str(value: Any) -> str:
    """Render a YAML scalar the way GitHub Actions passes it on.

    GitHub sees ``true`` / ``false`` / empty, not Python's ``True`` / ``None``.

    >>> _scalar_to_str(True), _scalar_to_str(False), _scalar_to_str(None)
    ('true', 'false', '')
    >>> _scalar_to_str(3), _scalar_to_str("x")
    ('3', 'x')
    """
    # ruamel returns an anchored/aliased boolean as ScalarBoolean (an int subclass)
    if isinstance(value, (bool, ScalarBoolean)):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _if_condition(value: Any) -> str | None:
    """An ``if:`` value as expression text (``if: false`` is the expression ``false``).

    >>> _if_condition(False), _if_condition(None), _if_condition("always()")
    ('false', None, 'always()')
    """
    return None if value is None else _scalar_to_str(value)


def _continue_on_error(value: Any) -> bool | str:
    """``continue-on-error``: a boolean, or an expression kept as text.

    >>> _continue_on_error(True), _continue_on_error("${{ matrix.exp }}")
    (True, '${{ matrix.exp }}')
    >>> _continue_on_error("false"), _continue_on_error(None)
    (False, False)
    """
    if value is None:
        return False
    if isinstance(value, str):
        lowered = value.strip().lower()
        return {"true": True, "false": False}.get(lowered, value)
    return bool(value)


def _str_map(mapping: dict | None, *, where: str) -> dict[str, str]:
    """A ``with:`` / ``env:`` mapping with every key and value a string.

    *where* names the mapping in the error for a non-scalar value (GitHub
    accepts only scalars there).

    >>> _str_map({"a": True, "b": 2}, where="x")
    {'a': 'true', 'b': '2'}
    """
    result: dict[str, str] = {}
    for key, value in (mapping or {}).items():
        if isinstance(value, (dict, list)):
            raise RecipeParseError(
                f"{where}: '{key}' must be a scalar, got a "
                f"{'mapping' if isinstance(value, dict) else 'list'}."
            )
        result[_scalar_to_str(key)] = _scalar_to_str(value)
    return result


def _parse_step(step_data: dict, *, index: int, job_id: str) -> StepSpec:
    uses = step_data.get("uses")
    run = step_data.get("run")
    if uses and run:
        raise RecipeParseError(
            f"Step {index} in job '{job_id}' has both 'uses' and 'run'."
        )
    if not uses and not run:
        raise RecipeParseError(
            f"Step {index} in job '{job_id}' has neither 'uses' nor 'run'."
        )

    step_id = step_data.get("id") or _auto_step_id(
        step_data, index=index, job_id=job_id
    )

    outputs = step_data.get("outputs", [])
    if isinstance(outputs, str):
        outputs = [outputs]

    bind = step_data.get("bind", {})
    with_ = _str_map(step_data.get("with"), where=f"Job '{job_id}' step {index} with:")

    return StepSpec(
        id=step_id,
        uses=uses,
        run=run,
        with_=with_,
        if_=_if_condition(step_data.get("if")),
        name=step_data.get("name"),
        outputs=outputs,
        bind=bind,
        env=_str_map(step_data.get("env"), where=f"Job '{job_id}' step {index} env:"),
    )


def _ensure_unique_step_ids(steps: list[StepSpec], *, job_id: str) -> list[StepSpec]:
    """Deduplicate step IDs within a job by appending a numeric suffix."""
    seen: dict[str, int] = {}
    result: list[StepSpec] = []
    for step in steps:
        base = step.id
        count = seen.get(base, 0)
        if count > 0:
            new_id = f"{base}_{count}"
            step = StepSpec(
                id=new_id,
                uses=step.uses,
                run=step.run,
                with_=step.with_,
                if_=step.if_,
                name=step.name,
                outputs=step.outputs,
                bind=step.bind,
                env=step.env,
            )
        seen[base] = count + 1
        result.append(step)
    return result


def _parse_job(job_id: str, job_data: dict) -> JobSpec:
    raw_steps = job_data.get("steps", [])
    if not raw_steps:
        raise RecipeParseError(f"Job '{job_id}' has no steps.")

    steps = [_parse_step(s, index=i, job_id=job_id) for i, s in enumerate(raw_steps)]
    steps = _ensure_unique_step_ids(steps, job_id=job_id)

    needs = job_data.get("needs", [])
    if isinstance(needs, str):
        needs = [needs]

    return JobSpec(
        id=job_id,
        steps=steps,
        needs=needs,
        if_=_if_condition(job_data.get("if")),
        runs_on=job_data.get("runs-on", "ubuntu-latest"),
        strategy=job_data.get("strategy"),
        permissions=job_data.get("permissions"),
        continue_on_error=_continue_on_error(job_data.get("continue-on-error")),
        env=_str_map(job_data.get("env"), where=f"Job '{job_id}' env:"),
    )


def parse_recipe(path: str) -> Recipe:
    """Load a recipe YAML and return a :class:`Recipe`."""
    data = load_yaml(path)
    if not isinstance(data, dict):
        raise RecipeParseError(f"Recipe file '{path}' is not a YAML mapping.")

    name = data.get("name", "")
    on = data.get("on", data.get(True, []))  # PyYAML compat: `on:` → True key
    jobs_data = data.get("jobs", {})
    if not jobs_data:
        raise RecipeParseError(f"Recipe file '{path}' has no jobs.")

    jobs = {jid: _parse_job(jid, jdata) for jid, jdata in jobs_data.items()}

    return Recipe(
        name=name,
        on=on,
        jobs=jobs,
        env=_str_map(data.get("env"), where="Workflow env:"),
        defaults=data.get("defaults"),
    )


def parse_recipe_string(text: str) -> Recipe:
    """Parse a recipe from a YAML string (useful for testing)."""
    from reci.yaml_gen import load_yaml_string

    data = load_yaml_string(text)
    if not isinstance(data, dict):
        raise RecipeParseError("Recipe is not a YAML mapping.")

    name = data.get("name", "")
    on = data.get("on", data.get(True, []))
    jobs_data = data.get("jobs", {})
    if not jobs_data:
        raise RecipeParseError("Recipe has no jobs.")

    jobs = {jid: _parse_job(jid, jdata) for jid, jdata in jobs_data.items()}

    return Recipe(
        name=name,
        on=on,
        jobs=jobs,
        env=_str_map(data.get("env"), where="Workflow env:"),
        defaults=data.get("defaults"),
    )
