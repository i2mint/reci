"""Config validation rules (CONF001–CONF003)."""

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
                refs.add(f'{local}__{norm_name}')
            refs.add(norm_name)
    return refs


@register_rule('CONF001')
def check_missing_required_config(
    graph, config: dict[str, Any]
) -> Iterable[Finding]:
    """Config keys that are required but not present."""
    for node in graph.nodes():
        for norm_name, input_spec in node.input_specs.items():
            if not input_spec.required:
                continue
            if input_spec.default is not None:
                continue
            if norm_name in {normalize_name(k) for k in node.with_}:
                continue
            # Check upstream outputs
            has_upstream = False
            search_name = node.bind.get(norm_name, norm_name)
            for prev in graph.job_nodes(node.job):
                if prev.key == node.key:
                    break
                if search_name in prev.output_names:
                    has_upstream = True
                    break
            if has_upstream:
                continue
            # Now check config
            if node.ref:
                local = action_local_name(node.ref)
                scoped = f'{local}__{norm_name}'
                if scoped in config:
                    continue
            if norm_name in config:
                continue
            yield Finding(
                rule_id='CONF001',
                severity=Severity.ERROR,
                message=(
                    f"Required config key '{norm_name}' (for '{node.key}') "
                    f"is missing from config."
                ),
                location=node.key,
            )


@register_rule('CONF003')
def check_unused_config(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """Config keys present but not referenced by any action."""
    referenced = _all_config_references(graph)
    for key in config:
        if key not in referenced:
            yield Finding(
                rule_id='CONF003',
                severity=Severity.INFO,
                message=f"Config key '{key}' is not referenced by any action input.",
            )
