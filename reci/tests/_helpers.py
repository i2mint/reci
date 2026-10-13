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
