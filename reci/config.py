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
from reci.graph import RecipeGraph
from reci.recipe import Recipe
from reci.recipe_checks import config_references


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
        scoped = f"{local}__{input_name}"
        if scoped in config:
            return scoped, config[scoped]
    if input_name in config:
        return input_name, config[input_name]
    return None


def flatten_config(nested: dict, *, prefix: str = "") -> dict[str, Any]:
    """Convert a nested dict to a flat dict with ``__`` separators.

    >>> flatten_config({'testing': {'python_versions': ['3.10']}})
    {'testing__python_versions': ['3.10']}
    """
    result: dict[str, Any] = {}
    for k, v in nested.items():
        full_key = f"{prefix}__{k}" if prefix else k
        if isinstance(v, dict):
            result.update(flatten_config(v, prefix=full_key))
        else:
            result[full_key] = v
    return result


def scaffold_placeholder_keys(
    recipe: Recipe,
    action_specs: dict[str, ActionSpec],
    existing: dict[str, Any],
) -> list[str]:
    """Config keys ``scaffold`` should add as ``<REQUIRED: ...>`` placeholders.

    Like the required part of :func:`collect_required_config_keys`, with two refinements: a key
    that one step requires but another step takes as optional is scoped
    (``<action>__<key>``) so the placeholder cannot shadow the optional step's default; and a
    required key already present in scoped form for every step that needs it is not asked for
    again unscoped.
    """
    graph = RecipeGraph.from_recipe(recipe, action_specs)
    existing_ids = {k.casefold() for k in existing if isinstance(k, str)}
    uses: dict[str, list[tuple[str | None, bool]]] = {}
    for node in graph.nodes():
        provided = {normalize_name(k) for k in node.with_}
        same_job = graph.upstream_output_names(node, other_jobs=False)
        everywhere = graph.upstream_output_names(node)
        for norm_name, inp in node.input_specs.items():
            search = node.bind.get(norm_name, norm_name)
            if norm_name in provided or search in same_job or search in everywhere:
                continue
            scoped = f"{action_local_name(node.ref)}__{norm_name}" if node.ref else None
            uses.setdefault(norm_name, []).append(
                (scoped, inp.required and inp.default is None)
            )
    for _, name, needs_ok in config_references(recipe):
        if needs_ok:  # the recipe itself names it: needed unscoped
            uses.setdefault(name, []).append((None, True))
    out: list[str] = []
    for name, items in uses.items():
        required = [scoped for scoped, req in items if req]
        if not required or name in existing or name.casefold() in existing_ids:
            continue
        if all(scoped and scoped in existing for scoped in required):
            continue
        if len(required) < len(
            items
        ):  # shared with an optional step: keep the placeholder scoped
            out.extend(sc or name for sc in required if sc not in existing)
        else:
            out.append(name)
    return list(dict.fromkeys(out))


def collect_required_config_keys(
    recipe: Recipe,
    action_specs: dict[str, ActionSpec],
) -> dict[str, bool]:
    """Scan a recipe and return config keys needed by its actions.

    Returns ``{key: required}`` where *required* is True when the input
    has ``required=True`` and no default.  Inputs given by an explicit
    ``with:`` or fed by an upstream step output (``bind:`` honoured) need no
    config key.  Keys the recipe references as ``${{ config.X }}`` are required.
    """
    graph = RecipeGraph.from_recipe(recipe, action_specs)
    keys: dict[str, bool] = {}

    def record(name: str, is_required: bool) -> None:
        keys[name] = keys.get(name, False) or is_required

    for node in graph.nodes():
        provided = {normalize_name(k) for k in node.with_}
        same_job = graph.upstream_output_names(node, other_jobs=False)
        everywhere = graph.upstream_output_names(node)
        for norm_name, inp in node.input_specs.items():
            if norm_name in provided:
                continue
            search = node.bind.get(norm_name, norm_name)
            is_required = inp.required and inp.default is None
            if search in same_job:
                continue
            if search not in everywhere:  # fed from another job: needs no key
                record(norm_name, is_required)

    # Keys the recipe itself references as ${{ config.X }} must exist too.
    for _, name, needs_ok in config_references(recipe):
        if needs_ok:
            record(name, True)
    return keys
