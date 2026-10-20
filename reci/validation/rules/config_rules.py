"""Config validation rules (CONF001–CONF007)."""

from __future__ import annotations

from typing import Any, Iterable

from reci.action_spec import normalize_name, action_local_name
from reci.validation.report import Finding, Severity
from reci.validation.rules import register_rule


def _all_config_references(graph) -> set[str]:
    """Collect all config keys referenced by any node's input resolution."""
    refs: set[str] = set()
    for node in graph.nodes():
        for norm_name in node.input_specs:
            if norm_name in {normalize_name(k) for k in node.with_}:
                continue
            # Scoped key
            if node.ref:
                local = action_local_name(node.ref)
                refs.add(f"{local}__{norm_name}")
            refs.add(norm_name)
    return refs


@register_rule("CONF001")
def check_missing_required_config(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """Config keys that are required but not present."""
    for node in graph.nodes():
        for norm_name, input_spec in node.input_specs.items():
            if not input_spec.required:
                continue
            if input_spec.default is not None:
                continue
            if norm_name in {normalize_name(k) for k in node.with_}:
                continue
            # Check upstream outputs (earlier steps in the job, or other jobs)
            search_name = node.bind.get(norm_name, norm_name)
            if search_name in graph.upstream_output_names(node):
                continue
            # Now check config
            if node.ref:
                local = action_local_name(node.ref)
                scoped = f"{local}__{norm_name}"
                if scoped in config:
                    continue
            if norm_name in config:
                continue
            yield Finding(
                rule_id="CONF001",
                severity=Severity.ERROR,
                message=(
                    f"Required config key '{norm_name}' (for '{node.key}') "
                    f"is missing from config."
                ),
                location=node.key,
            )


@register_rule("CONF003")
def check_unused_config(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """Config keys present but not referenced by any action."""
    referenced = _all_config_references(graph)
    for key in config:
        if key not in referenced:
            yield Finding(
                rule_id="CONF003",
                severity=Severity.INFO,
                message=f"Config key '{key}' is not referenced by any action input.",
            )


@register_rule("CONF004")
def check_undefined_config_references(
    graph, config: dict[str, Any]
) -> Iterable[Finding]:
    """``${{ config.X }}`` where ``X`` is not a config key."""
    from reci.validation.rules.dag import _recipe_problems

    yield from _recipe_problems(graph, config, "CONF004")


@register_rule("CONF005")
def check_exportable_config(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """Config keys must be valid output ids; values must survive $GITHUB_OUTPUT."""
    from reci.validation.rules.dag import _recipe_problems

    yield from _recipe_problems(graph, config, "CONF005")


@register_rule("CONF006")
def check_empty_value_shadows_default(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """An empty-string config value on an input that has an action default (it replaces it)."""
    seen: set[str] = set()
    for node in graph.nodes():
        for norm_name, input_spec in node.input_specs.items():
            if input_spec.default is None:
                continue
            keys = [norm_name]
            if node.ref:
                keys.insert(0, f"{action_local_name(node.ref)}__{norm_name}")
            for key in keys:
                if config.get(key) == "" and (key, node.key) not in seen:
                    seen.add((key, node.key))
                    yield Finding(
                        rule_id="CONF006",
                        severity=Severity.WARNING,
                        message=(
                            f"Config key '{key}' is an empty string, which overrides the "
                            f"default ({input_spec.default!r}) of '{node.key}'; remove the key."
                        ),
                        location=node.key,
                    )
                    break


@register_rule("CONF007")
def check_leftover_placeholders(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """``<REQUIRED: ...>`` values that ``reci scaffold`` wrote and nobody filled in."""
    for key, value in config.items():
        if isinstance(value, str) and value.lstrip().startswith("<REQUIRED:"):
            yield Finding(
                rule_id="CONF007",
                severity=Severity.ERROR,
                message=f"Config key '{key}' still holds the scaffold placeholder {value!r}; set a real value.",
            )


@register_rule("CONF008")
def check_boolean_config_condition(
    graph, config: dict[str, Any]
) -> Iterable[Finding]:
    """An ``if:`` that is only a boolean config value: config values are strings."""
    from reci.recipe_checks import bool_config_conditions

    if graph.recipe is None:
        return
    for location, key in bool_config_conditions(graph.recipe, config):
        yield Finding(
            rule_id="CONF008",
            severity=Severity.WARNING,
            message=(
                f"'{location}' has an if: that is just config.{key}, but config values "
                f"reach the workflow as strings, so the condition is true even for "
                f"'false'."
            ),
            location=location,
            suggestion=f"Compare it: config.{key} == 'true'.",
        )
