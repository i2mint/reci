"""Data-flow validation rules (FLOW001–FLOW006)."""

from __future__ import annotations

from typing import Any, Iterable

from reci.action_spec import normalize_name, action_local_name
from reci.validation.report import Finding, Severity
from reci.validation.rules import register_rule


def _resolve_config_key(
    input_name: str, ref: str | None, config: dict[str, Any]
) -> str | None:
    if ref:
        local = action_local_name(ref)
        scoped = f"{local}__{input_name}"
        if scoped in config:
            return scoped
    if input_name in config:
        return input_name
    return None


def _build_upstream_outputs(graph, job_id: str, up_to_key: str) -> dict[str, str]:
    """Output names -> step_id for steps preceding up_to_key in the same job."""
    outputs: dict[str, str] = {}
    for node in graph.job_nodes(job_id):
        if node.key == up_to_key:
            break
        for name in node.output_names:
            outputs[name] = node.step_id
    return outputs


@register_rule("FLOW001")
def check_unsourced_required_inputs(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """Required input has no source at any level."""
    for node in graph.nodes():
        upstream = _build_upstream_outputs(graph, node.job, node.key)
        for norm_name, input_spec in node.input_specs.items():
            if not input_spec.required:
                continue
            # Level 1: explicit with:
            if norm_name in {normalize_name(k) for k in node.with_}:
                continue
            search_name = node.bind.get(norm_name, norm_name)
            # Level 2: upstream output
            if search_name in upstream:
                continue
            # Level 3: config
            if _resolve_config_key(norm_name, node.ref, config) is not None:
                continue
            # Level 4: default
            if input_spec.default is not None:
                continue
            # Level 5: error
            yield Finding(
                rule_id="FLOW001",
                severity=Severity.ERROR,
                message=(
                    f"Required input '{input_spec.name}' of '{node.key}' "
                    f"has no source (no explicit with:, upstream output, "
                    f"config value, or default)."
                ),
                location=node.key,
            )


@register_rule("FLOW002")
def check_ambiguous_wiring(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """An input name matches multiple upstream outputs."""
    for node in graph.nodes():
        for norm_name, input_spec in node.input_specs.items():
            if norm_name in {normalize_name(k) for k in node.with_}:
                continue
            search_name = node.bind.get(norm_name, norm_name)
            # Count matches in upstream
            matches: list[str] = []
            for prev_node in graph.job_nodes(node.job):
                if prev_node.key == node.key:
                    break
                if search_name in prev_node.output_names:
                    matches.append(prev_node.step_id)
            if len(matches) > 1:
                yield Finding(
                    rule_id="FLOW002",
                    severity=Severity.WARNING,
                    message=(
                        f"Input '{input_spec.name}' of '{node.key}' matches "
                        f"outputs from multiple upstream steps: "
                        f"{', '.join(matches)}. Using nearest predecessor."
                    ),
                    location=node.key,
                )


@register_rule("FLOW004")
def check_unused_outputs(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """An output is declared but never consumed downstream."""
    consumed: set[str] = set()
    for node in graph.nodes():
        for norm_name in node.input_specs:
            search = node.bind.get(norm_name, norm_name)
            consumed.add(search)
        # Also count explicit with: values that reference steps
        for v in node.with_.values():
            if "steps." in str(v) and ".outputs." in str(v):
                consumed.add(str(v))

    for node in graph.nodes():
        for name in node.output_names:
            if name not in consumed:
                yield Finding(
                    rule_id="FLOW004",
                    severity=Severity.INFO,
                    message=(
                        f"Output '{name}' of '{node.key}' "
                        f"is not consumed by any downstream step."
                    ),
                    location=node.key,
                )


@register_rule("FLOW005")
def check_boolean_coercion(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """A string output is wired to a likely-boolean input."""
    for node in graph.nodes():
        for norm_name, input_spec in node.input_specs.items():
            is_boolean = input_spec.default is not None and str(
                input_spec.default
            ).lower() in ("true", "false")
            if not is_boolean:
                continue
            # Check if this input is wired from an upstream output
            if norm_name in {normalize_name(k) for k in node.with_}:
                continue
            search_name = node.bind.get(norm_name, norm_name)
            upstream = _build_upstream_outputs(graph, node.job, node.key)
            if search_name in upstream:
                yield Finding(
                    rule_id="FLOW005",
                    severity=Severity.WARNING,
                    message=(
                        f"Input '{input_spec.name}' of '{node.key}' "
                        f"appears boolean (default='{input_spec.default}') "
                        f"but will receive a string from upstream output. "
                        f"Use == 'true' comparison."
                    ),
                    location=node.key,
                    suggestion="Use ${{ steps.<id>.outputs.<name> == 'true' }}",
                )


@register_rule("FLOW006")
def check_matrix_output(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """Matrix job outputs consumed by downstream are non-deterministic."""
    # This requires knowing which jobs have matrix strategies.
    # We check via the graph's recipe reference (stored on JobSpec).
    # For now, check if any job node has strategy info in the graph metadata.
    # Since we don't store strategy on ActionNode, this is checked at
    # compile time via the recipe. Stub for now — will be enhanced.
    return []
