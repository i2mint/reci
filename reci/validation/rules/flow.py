"""Data-flow validation rules (FLOW001–FLOW006)."""

from __future__ import annotations

import re
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
        # same job (earlier steps) or any other job: the compiler forwards those
        upstream = graph.upstream_output_names(node)
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
                    f"Required input '{input_spec.emitted_name}' of '{node.key}' "
                    f"has no source (no explicit with:, upstream output, "
                    f"config value, or default)."
                ),
                location=node.key,
            )


@register_rule("FLOW002")
def check_ambiguous_wiring(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """An input name matches multiple upstream outputs, in a job or across jobs.

    Within a job the nearest preceding step wins.  Across jobs there is no
    nearer: the first producing job in recipe order is used.
    """
    from reci.compiler import detect_cross_job_edges

    for edge in detect_cross_job_edges(graph, config):
        if edge.alternatives:
            yield Finding(
                rule_id="FLOW002",
                severity=Severity.WARNING,
                message=(
                    f"Input '{edge.target_input}' of "
                    f"'{edge.target_job}.{edge.target_step_id}' matches outputs "
                    f"from several jobs: {edge.source_job}, "
                    f"{', '.join(edge.alternatives)}. Using the first, "
                    f"'{edge.source_job}'."
                ),
                location=f"{edge.target_job}.{edge.target_step_id}",
                suggestion=(
                    "Name the outputs differently and pick one with bind:, or "
                    "give the input an explicit with:."
                ),
            )
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
                        f"Input '{input_spec.emitted_name}' of '{node.key}' matches "
                        f"outputs from multiple upstream steps: "
                        f"{', '.join(matches)}. Using nearest predecessor."
                    ),
                    location=node.key,
                )


# ``steps.<id>.outputs.<name>`` in dot or bracket syntax, in any mix.
_STEP_OUTPUT_REF = re.compile(
    r"""\bsteps(?:\.|\s*\[\s*['"])([\w-]+)(?:['"]\s*\])?\s*\.\s*outputs"""
    r"""(?:\s*\.\s*|\s*\[\s*['"])([\w-]+)"""
)


def _strings_in(value) -> Iterable[str]:
    """Every string anywhere inside a (possibly nested) value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):  # values only: a key can never hold an expression
        for v in value.values():
            yield from _strings_in(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings_in(v)


def _job_texts(graph, job_id: str) -> Iterable[str]:
    """Every string of a step of *job_id* where the ``steps`` context is available.

    A job's own ``if``/``strategy``/``env``/``continue-on-error`` cannot see
    ``steps``, so a reference there never resolves and does not count.
    """
    if graph.recipe is not None and job_id in graph.recipe.jobs:
        job = graph.recipe.jobs[job_id]
        yield from _strings_in(job.extra.get("outputs"))  # a job output sees steps
        for step in job.steps:
            yield from _strings_in(
                (step.with_, step.env, step.run, step.if_, step.name)
                + (step.continue_on_error, step.extra)
            )
        return
    for node in graph.job_nodes(job_id):
        yield from _strings_in((node.with_, node.env, node.run, node.if_, node.name))


@register_rule("FLOW004")
def check_unused_outputs(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """An output is declared but never consumed downstream.

    Consumed means: matched by an input of a later step (by name, honouring
    ``bind:``), or referenced explicitly as ``steps.<id>.outputs.<name>`` (dot or
    bracket syntax, ids compared case-insensitively) in a step of the same job:
    its ``with:``, ``env:``, ``run:``, ``if:``, ``name:`` or other keys, or in a
    job ``outputs:`` entry (a job's other fields cannot read ``steps``).
    ``needs.`` references are not counted: only the compiler's own forwarding and
    the job ``outputs:`` the recipe declares make them resolve.
    """
    consumed: set[str] = set()  # normalized output names
    referenced: set[tuple[str, str, str]] = set()  # (job, step id, output name)
    for node in graph.nodes():
        for norm_name in node.input_specs:
            consumed.add(node.bind.get(norm_name, norm_name))

    for job_id in graph.job_ids():
        for text in _job_texts(graph, job_id):
            for step_id, name in _STEP_OUTPUT_REF.findall(text):
                referenced.add((job_id, step_id.lower(), normalize_name(name)))

    for node in graph.nodes():
        for name in node.output_names:
            if (
                name not in consumed
                and (node.job, node.step_id.lower(), name) not in referenced
            ):
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
                        f"Input '{input_spec.emitted_name}' of '{node.key}' "
                        f"appears boolean (default='{input_spec.default}') "
                        f"but will receive a string from upstream output. "
                        f"Use == 'true' comparison."
                    ),
                    location=node.key,
                    suggestion="Use ${{ steps.<id>.outputs.<name> == 'true' }}",
                )


@register_rule("FLOW006")
def check_matrix_output(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """A job output consumed by another job comes from a matrix or conditional job.

    A matrix job has one output value for all its legs: whichever leg finishes
    last wins.  A job with an ``if:`` that is false is skipped, and so is every
    job that ``needs`` it (unless it uses ``always()`` or similar).
    """
    from reci.compiler import detect_cross_job_edges

    if graph.recipe is None:
        return
    reported: set[tuple[str, str, str]] = set()
    for edge in detect_cross_job_edges(graph, config):
        job = graph.recipe.jobs[edge.source_job]
        where = f"'{edge.source_job}.{edge.source_step_id}'"
        reads = (
            f"'{edge.target_job}.{edge.target_step_id}' reads "
            f"'{edge.source_output}' from {where}"
        )
        if isinstance(job.strategy, dict) and "matrix" in job.strategy:
            if (edge.source_job, edge.source_output, "matrix") not in reported:
                reported.add((edge.source_job, edge.source_output, "matrix"))
                yield Finding(
                    rule_id="FLOW006",
                    severity=Severity.WARNING,
                    message=(
                        f"{reads}, but job '{edge.source_job}' is a matrix: its "
                        f"output is the value of whichever leg finishes last."
                    ),
                    location=where.strip("'"),
                    suggestion=(
                        "Produce the value in a job without a matrix, or "
                        "aggregate the legs yourself."
                    ),
                )
        if job.if_ and (edge.source_job, edge.source_output, "if") not in reported:
            reported.add((edge.source_job, edge.source_output, "if"))
            yield Finding(
                rule_id="FLOW006",
                severity=Severity.WARNING,
                message=(
                    f"{reads}, but job '{edge.source_job}' has an if: "
                    f"({job.if_}); when it is skipped, so is '{edge.target_job}' "
                    f"(and the output is empty)."
                ),
                location=where.strip("'"),
                suggestion=(
                    "Give the consumer job an if: such as always() && ..., or "
                    "move the condition to the step."
                ),
            )
