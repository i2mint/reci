"""Recipe model — declarative CI pipeline description.

A recipe is a YAML file that looks like a GitHub Actions workflow but with
reci extensions: ``${{ config.* }}`` references, ``bind:`` mappings for
input renaming, and ``outputs:`` annotations on ``run:`` steps.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field, replace
from typing import Any

from ruamel.yaml.scalarbool import ScalarBoolean

from reci.action_spec import normalize_name
from reci.yaml_gen import load_yaml, load_yaml_string, scalar_source_text


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
    continue_on_error: bool | str = False  # a bool, or an expression string
    extra: dict[str, Any] = field(default_factory=dict)  # other keys, kept verbatim


@dataclass(frozen=True)
class JobSpec:
    """One job inside a recipe."""

    id: str
    steps: list[StepSpec] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)
    if_: str | None = None
    runs_on: str | list | dict = "ubuntu-latest"
    strategy: dict | None = None
    permissions: dict | None = None
    continue_on_error: bool | str = False  # a bool, or an expression string
    env: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)  # other keys, kept verbatim


@dataclass(frozen=True)
class Recipe:
    """A complete reci recipe."""

    name: str
    on: Any  # str | list | dict — GitHub Actions trigger spec
    jobs: dict[str, JobSpec] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    defaults: dict | None = None
    extra: dict[str, Any] = field(default_factory=dict)  # other keys, kept verbatim


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
    >>> _scalar_to_str(load_yaml_string("v: 3.10")["v"])
    '3.10'
    """
    # ruamel returns an anchored/aliased boolean as ScalarBoolean (an int subclass)
    if isinstance(value, (bool, ScalarBoolean)):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        # Keep the spelling the author wrote: str() turns 3.10 into 3.1
        return scalar_source_text(value)
    return str(value)


def _require_scalar(value: Any, *, where: str) -> None:
    if isinstance(value, (dict, list)):
        kind = "mapping" if isinstance(value, dict) else "list"
        raise RecipeParseError(f"{where} must be a scalar, got a {kind}.")


def _if_condition(value: Any, *, where: str) -> str | None:
    """An ``if:`` value as expression text (``if: false`` is the expression ``false``).

    >>> _if_condition(False, where="x"), _if_condition(None, where="x")
    ('false', None)
    >>> _if_condition("always()", where="x")
    'always()'
    """
    _require_scalar(value, where=where)
    return None if value is None else _scalar_to_str(value)


def _continue_on_error(value: Any, *, where: str) -> bool | str:
    """``continue-on-error``: a boolean, or an expression kept as text.

    >>> _continue_on_error(True, where="x")
    True
    >>> _continue_on_error("${{ matrix.exp }}", where="x")
    '${{ matrix.exp }}'
    >>> _continue_on_error("false", where="x"), _continue_on_error(None, where="x")
    (False, False)
    """
    _require_scalar(value, where=where)
    if value is None:
        return False
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "false"):
            return lowered == "true"
        if "${{" not in value:
            raise RecipeParseError(
                f"{where} must be a boolean or a ${{{{ }}}} expression, got {value!r}."
            )
        return value
    return bool(value)


_DECIMAL_RE = re.compile(r"[+-]?\d*\.\d+")


def _spell_numbers(obj: Any, *, decimals_only: bool = False) -> Any:
    """*obj* with each number whose source spelling ``str()`` loses kept as text.

    GitHub reads an unquoted ``3.10`` in a matrix as the number 3.1; quoting the
    author's spelling keeps ``3.10``.  Other numbers are left alone.  With
    *decimals_only*, only decimal spellings (``3.10``, ``1.50``) count: hex or
    exponent numbers keep meaning what YAML says they mean.

    >>> _spell_numbers(load_yaml_string("m: [3.10, 3.9, 7, 0x10, x]")["m"],
    ...                decimals_only=True)
    ['3.10', 3.9, 7, 16, 'x']
    """
    if isinstance(obj, dict):
        return {
            k: _spell_numbers(v, decimals_only=decimals_only) for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_spell_numbers(v, decimals_only=decimals_only) for v in obj]
    if isinstance(obj, (int, float)) and not isinstance(obj, (bool, ScalarBoolean)):
        text = scalar_source_text(obj)
        if text != str(obj) and (not decimals_only or _DECIMAL_RE.fullmatch(text)):
            return text
    return obj


def _spell_env_numbers(obj: Any) -> Any:
    """*obj* with the numbers under any ``env`` key spelled as written.

    ``env`` values are strings for GitHub (``container.env``, ``services.<id>.env``);
    other keys (``timeout-minutes``, ``ports``) are typed and keep their numbers.
    """
    if isinstance(obj, dict):
        return {
            k: _spell_numbers(v) if k == "env" else _spell_env_numbers(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_spell_env_numbers(v) for v in obj]
    return obj


def _strategy(value: Any) -> dict | None:
    """A ``strategy:`` mapping with the numbers of its ``matrix`` spelled as written."""
    if isinstance(value, dict) and "matrix" in value:
        return {**value, "matrix": _spell_numbers(value["matrix"], decimals_only=True)}
    return value


def _extra(data: dict, known: frozenset) -> dict[str, Any]:
    """The keys of *data* reci does not model, kept so they reach the workflow.

    ``timeout-minutes``, ``container``, ``services``, ``concurrency``, ``shell``,
    ``working-directory``... are plain GitHub keys with no recipe meaning;
    dropping them silently would change what the workflow does.  Keys starting
    with ``x-`` or ``.`` are the YAML idiom for holding anchors and are dropped:
    GitHub rejects them.

    >>> _extra({"id": "a", "shell": "bash", "x-common": {"k": 1}}, frozenset({"id"}))
    {'shell': 'bash'}
    """
    return {
        k: _spell_env_numbers(v)
        for k, v in data.items()
        if k not in known and not (isinstance(k, str) and k.startswith(("x-", ".")))
    }


_STEP_KEYS = frozenset(
    {"id", "uses", "run", "with", "if", "name", "outputs", "bind", "env"}
    | {"continue-on-error"}
)
_JOB_KEYS = frozenset(
    {"steps", "needs", "if", "runs-on", "strategy", "permissions", "env"}
    | {"continue-on-error"}
)
_RECIPE_KEYS = frozenset({"name", "on", True, "jobs", "env", "defaults"})


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

    step_id = _scalar_to_str(step_data.get("id") or "") or _auto_step_id(
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
        if_=_if_condition(
            step_data.get("if"), where=f"Job '{job_id}' step {index} if:"
        ),
        name=step_data.get("name"),
        outputs=outputs,
        bind=bind,
        env=_str_map(step_data.get("env"), where=f"Job '{job_id}' step {index} env:"),
        continue_on_error=_continue_on_error(
            step_data.get("continue-on-error"),
            where=f"Job '{job_id}' step {index} continue-on-error:",
        ),
        extra=_extra(step_data, _STEP_KEYS),
    )


def _ensure_unique_step_ids(
    steps: list[StepSpec], *, explicit: list[bool], job_id: str
) -> list[StepSpec]:
    """Make step ids unique within a job (GitHub compares them case-insensitively).

    A step id the author wrote is never changed: two of them that collide are an
    error.  A derived id (from ``uses:``) that collides gets the first free
    ``_1``, ``_2``... suffix, one that no other step uses.
    """
    taken: dict[str, str] = {}  # casefolded id -> spelling
    for step, written in zip(steps, explicit):
        if written:
            if step.id.casefold() in taken:
                raise RecipeParseError(
                    f"Job '{job_id}' has two steps with the id '{step.id}' "
                    f"(step ids are case-insensitive): "
                    f"{taken[step.id.casefold()]!r} and {step.id!r}."
                )
            taken[step.id.casefold()] = step.id
    result: list[StepSpec] = []
    for step, written in zip(steps, explicit):
        if not written:
            new_id, count = step.id, 0
            while new_id.casefold() in taken:
                count += 1
                new_id = f"{step.id}_{count}"
            taken[new_id.casefold()] = new_id
            step = replace(step, id=new_id)
        result.append(step)
    return result


def _job_extra(job_id: str, job_data: dict) -> dict[str, Any]:
    extra = _extra(job_data, _JOB_KEYS)
    if "outputs" in extra and not isinstance(extra["outputs"], dict):
        raise RecipeParseError(f"Job '{job_id}' outputs: must be a mapping.")
    return extra


def _parse_job(job_id: str, job_data: dict) -> JobSpec:
    raw_steps = job_data.get("steps", [])
    if not raw_steps:
        raise RecipeParseError(f"Job '{job_id}' has no steps.")

    steps = [_parse_step(s, index=i, job_id=job_id) for i, s in enumerate(raw_steps)]
    steps = _ensure_unique_step_ids(
        steps, explicit=[bool(s.get("id")) for s in raw_steps], job_id=job_id
    )

    needs = job_data.get("needs", [])
    if isinstance(needs, str):
        needs = [needs]

    return JobSpec(
        id=job_id,
        steps=steps,
        needs=needs,
        if_=_if_condition(job_data.get("if"), where=f"Job '{job_id}' if:"),
        runs_on=job_data.get("runs-on", "ubuntu-latest"),
        strategy=_strategy(job_data.get("strategy")),
        permissions=job_data.get("permissions"),
        continue_on_error=_continue_on_error(
            job_data.get("continue-on-error"),
            where=f"Job '{job_id}' continue-on-error:",
        ),
        env=_str_map(job_data.get("env"), where=f"Job '{job_id}' env:"),
        extra=_job_extra(job_id, job_data),
    )


def _recipe_from_data(data: Any, *, source: str) -> Recipe:
    if not isinstance(data, dict):
        raise RecipeParseError(f"{source} is not a YAML mapping.")
    jobs_data = data.get("jobs", {})
    if not jobs_data:
        raise RecipeParseError(f"{source} has no jobs.")

    return Recipe(
        name=data.get("name", ""),
        on=data.get("on", data.get(True, [])),  # PyYAML compat: `on:` → True key
        jobs={jid: _parse_job(jid, jdata) for jid, jdata in jobs_data.items()},
        env=_str_map(data.get("env"), where="Workflow env:"),
        defaults=data.get("defaults"),
        extra=_extra(data, _RECIPE_KEYS),
    )


def parse_recipe(path: str) -> Recipe:
    """Load a recipe YAML and return a :class:`Recipe`."""
    return _recipe_from_data(load_yaml(path), source=f"Recipe file '{path}'")


def parse_recipe_string(text: str) -> Recipe:
    """Parse a recipe from a YAML string (useful for testing)."""
    return _recipe_from_data(load_yaml_string(text), source="Recipe")
