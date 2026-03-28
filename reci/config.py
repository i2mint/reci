"""Config resolution — flat dict with scoped overrides.

Resolution order for input ``root_dir`` of action ``run-tests``::

    1. ``run_tests__root_dir`` in config → scoped override wins
    2. ``root_dir`` in config → shared default
    3. ``default`` from action.yml → action default
    4. If required and none found → validation error (FLOW001)
"""

from __future__ import annotations

from typing import Any

from reci.action_spec import ActionSpec, normalize_name, action_local_name
from reci.recipe import Recipe


def resolve_config_for_input(
    input_name: str,
    ref: str | None,
    config: dict[str, Any],
) -> tuple[str, Any] | None:
    """Find a config value for an action input.

    Returns ``(config_key, value)`` or ``None``.
    """
    if ref:
        local = action_local_name(ref)
        scoped = f'{local}__{input_name}'
        if scoped in config:
            return scoped, config[scoped]
    if input_name in config:
        return input_name, config[input_name]
    return None


def flatten_config(nested: dict, *, prefix: str = '') -> dict[str, Any]:
    """Convert a nested dict to a flat dict with ``__`` separators.

    >>> flatten_config({'testing': {'python_versions': ['3.10']}})
    {'testing__python_versions': ['3.10']}
    """
    result: dict[str, Any] = {}
    for k, v in nested.items():
        full_key = f'{prefix}__{k}' if prefix else k
        if isinstance(v, dict):
            result.update(flatten_config(v, prefix=full_key))
        else:
            result[full_key] = v
    return result


def collect_required_config_keys(
    recipe: Recipe,
    action_specs: dict[str, ActionSpec],
) -> dict[str, bool]:
    """Scan a recipe and return config keys needed by its actions.

    Returns ``{key: required}`` where *required* is True when the input
    has ``required=True`` and no default.
    """
    keys: dict[str, bool] = {}
    for job in recipe.jobs.values():
        for step in job.steps:
            spec = action_specs.get(step.uses) if step.uses else None
            if not spec:
                continue
            for norm_name, inp in spec.inputs.items():
                # Skip inputs that are explicitly provided
                if norm_name in {normalize_name(k) for k in step.with_}:
                    continue
                is_required = inp.required and inp.default is None
                # Record the shared key name
                if norm_name not in keys:
                    keys[norm_name] = is_required
                elif is_required:
                    keys[norm_name] = True
    return keys
