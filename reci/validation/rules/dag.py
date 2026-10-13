"""DAG structure validation rules (DAG001–DAG004)."""

from __future__ import annotations

from collections import Counter
from graphlib import CycleError, TopologicalSorter
from typing import Any, Iterable

from reci.graph import find_cycle
from reci.recipe_checks import find_recipe_problems
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
    from reci.compiler import describe_cycle_edges, detect_cross_job_edges

    edges = detect_cross_job_edges(graph, config)
    depends_on = {job_id: set(graph.job_needs(job_id)) for job_id in graph.job_ids()}
    for edge in edges:
        depends_on[edge.target_job].add(edge.source_job)

    # Every data-flow edge closes a loop if its producer already depends, through
    # needs: or other data flow, on its consumer.  Looking edge by edge also finds
    # a loop beside an explicit-needs loop (DAG001's).
    reported: set[frozenset[str]] = set()
    for edge in edges:
        path = _dependency_path(depends_on, edge.source_job, edge.target_job)
        if path is None:
            continue
        cycle = [edge.target_job, *path]
        if frozenset(cycle) in reported:
            continue
        reported.add(frozenset(cycle))
        reasons = describe_cycle_edges(cycle, edges)
        hops = set(zip(cycle, cycle[1:]))
        alternatives = [
            f"'{e.source_output}' is also produced by job "
            f"{', '.join(repr(j) for j in e.alternatives)}"
            for e in edges
            if (e.target_job, e.source_job) in hops and e.alternatives
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
                + (
                    f" The first producer in recipe order is used ("
                    f"{'; '.join(alternatives)}): give the outputs different "
                    f"names and pick one with bind: to use the other job."
                    if alternatives
                    else ""
                )
            ),
        )


def _dependency_path(
    depends_on: dict[str, set[str]], start: str, goal: str
) -> list[str] | None:
    """A path ``start -> ... -> goal`` following "depends on", or ``None``."""
    parents: dict[str, str | None] = {start: None}
    queue = [start]
    for node in queue:
        if node == goal:
            path = []
            while node is not None:
                path.append(node)
                node = parents[node]
            return path[::-1]
        for nxt in sorted(depends_on.get(node, ())):
            if nxt not in parents:
                parents[nxt] = node
                queue.append(nxt)
    return None


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


def _recipe_problems(graph, config: dict[str, Any], rule_id: str) -> Iterable[Finding]:
    """The recipe-level problems (see :mod:`reci.recipe_checks`) for *rule_id*."""
    if graph.recipe is None:
        return
    for problem in find_recipe_problems(graph.recipe, config):
        if problem.rule_id == rule_id:
            yield Finding(
                rule_id=rule_id,
                severity=Severity.ERROR,
                message=problem.message,
                location=problem.location,
            )


@register_rule("DAG006")
def check_needs_unknown_job(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """``needs:`` names a job that does not exist."""
    yield from _recipe_problems(graph, config, "DAG006")


@register_rule("DAG007")
def check_reserved_setup_job(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """A recipe job uses the id of the generated ``setup`` job."""
    yield from _recipe_problems(graph, config, "DAG007")
