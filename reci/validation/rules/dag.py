"""DAG structure validation rules (DAG001–DAG004)."""

from __future__ import annotations

from collections import Counter
from graphlib import CycleError, TopologicalSorter
from typing import Any, Iterable

from reci.graph import find_cycle
from reci.validation.report import Finding, Severity
from reci.validation.rules import register_rule


@register_rule("DAG001")
def check_cycles(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """Detect cycles in the dependency graph."""
    ts = TopologicalSorter(graph._deps)
    try:
        ts.prepare()
    except CycleError as e:
        cycle = e.args[1] if len(e.args) > 1 else []
        yield Finding(
            rule_id="DAG001",
            severity=Severity.ERROR,
            message=f"Cycle detected: {' -> '.join(str(n) for n in cycle)}",
        )


@register_rule("DAG005")
def check_data_flow_needs_cycles(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """Data flow between jobs must not make their ``needs`` form a cycle.

    The compiler adds a ``needs`` edge from every consumer job to the job that
    produces an output it reads.  Combined with explicit ``needs:`` (or with the
    reverse flow) that can close a loop, which GitHub rejects.  A cycle made of
    explicit ``needs:`` alone is DAG001's.
    """
    from reci.compiler import detect_cross_job_edges

    explicit = {job_id: list(graph.job_needs(job_id)) for job_id in graph.job_ids()}
    if find_cycle(explicit):
        return
    edges = detect_cross_job_edges(graph, config)
    combined = {job_id: set(needs) for job_id, needs in explicit.items()}
    for edge in edges:
        combined[edge.target_job].add(edge.source_job)
    cycle = find_cycle(combined)
    if not cycle:
        return
    reasons = [
        f"'{e.target_job}.{e.target_step_id}' reads '{e.source_output}' "
        f"from '{e.source_job}.{e.source_step_id}'"
        for e in edges
        for consumer, producer in zip(cycle, cycle[1:])
        if (e.target_job, e.source_job) == (consumer, producer)
    ]
    yield Finding(
        rule_id="DAG005",
        severity=Severity.ERROR,
        message=(
            f"Job dependencies form a cycle: {' -> '.join(cycle)} "
            f"(inferred from data flow: {'; '.join(reasons) or 'n/a'})."
        ),
        location=cycle[0],
        suggestion=(
            "Break the loop: pass the value through config or an explicit "
            "with:, or move a step into the other job."
        ),
    )


@register_rule("DAG002")
def check_duplicate_outputs(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """Flag duplicate output names within a job (at the job output level)."""
    for job_id in graph.job_ids():
        output_sources: dict[str, list[str]] = {}
        for node in graph.job_nodes(job_id):
            for name in node.output_names:
                output_sources.setdefault(name, []).append(node.step_id)
        for name, sources in output_sources.items():
            if len(sources) > 1:
                yield Finding(
                    rule_id="DAG002",
                    severity=Severity.ERROR,
                    message=(
                        f"Duplicate output '{name}' in job '{job_id}' "
                        f"from steps: {', '.join(sources)}"
                    ),
                    location=job_id,
                )


@register_rule("DAG004")
def check_isolated_nodes(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """Flag nodes with no data connections (no outputs consumed, no inputs from graph)."""
    # Collect all consumed output names
    consumed: set[str] = set()
    for node in graph.nodes():
        for norm_name in node.input_specs:
            search = node.bind.get(norm_name, norm_name)
            consumed.add(search)

    for node in graph.nodes():
        has_consumed_output = any(n in consumed for n in node.output_names)
        has_graph_input = bool(node.input_specs)
        if not has_consumed_output and not has_graph_input and not node.run:
            yield Finding(
                rule_id="DAG004",
                severity=Severity.WARNING,
                message=f"Node '{node.key}' appears isolated (no data connections).",
                location=node.key,
            )
