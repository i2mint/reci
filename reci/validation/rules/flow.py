"""Data-flow validation rules (FLOW001–FLOW007)."""

from __future__ import annotations

import re
from typing import Any, Iterable

from reci.action_spec import normalize_name, action_local_name
from reci.recipe_checks import as_expression, expression_texts
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


# ``<context>.<id>.outputs.<name>`` in dot or bracket syntax, in any mix; GitHub
# contexts are case-insensitive.  Run over an expression with the string literals
# blanked (see ``expression_texts``), so only the quoted index of a bracket
# access survives.
_REF_TAIL = r"""(?:\s*\.\s*|\s*\[\s*')([\w-]+)(?:'\s*\])?\s*(?:\.\s*outputs|\[\s*'outputs'\s*\])(?:\s*\.\s*|\s*\[\s*')([\w-]+)"""
_STEP_OUTPUT_REF = re.compile(r"(?<![\w.\-])steps" + _REF_TAIL, re.IGNORECASE)
_NEEDS_OUTPUT_REF = re.compile(r"(?<![\w.\-])needs" + _REF_TAIL, re.IGNORECASE)


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


def _expressions(*fields, conditions: Iterable[str | None] = ()) -> Iterable[str]:
    """The expressions in *fields* (``${{ }}`` bodies) and bare *conditions* (``if:``)."""
    for text in _strings_in(fields):
        yield from expression_texts(text)
    for text in conditions:
        if text:
            yield from expression_texts(as_expression(text))


def _step_scopes(graph, job_id: str) -> list[list[str]]:
    """For each step of *job_id*, in order, the expressions where ``steps`` resolves."""
    if graph.recipe is not None and job_id in graph.recipe.jobs:
        return [
            list(
                _expressions(
                    step.with_,
                    step.env,
                    step.run,
                    step.name,
                    step.continue_on_error,
                    step.extra,
                    conditions=[step.if_],
                )
            )
            for step in graph.recipe.jobs[job_id].steps
        ]
    return [
        list(
            _expressions(
                node.with_, node.env, node.run, node.name, conditions=[node.if_]
            )
        )
        for node in graph.job_nodes(job_id)
    ]


def _job_output_scope(graph, job_id: str) -> list[str]:
    """Expressions of a job's ``outputs:``, which also see ``steps`` (after all steps)."""
    if graph.recipe is None or job_id not in graph.recipe.jobs:
        return []
    return list(_expressions(graph.recipe.jobs[job_id].extra.get("outputs")))


def _step_references(graph, job_id: str) -> Iterable[tuple[int, str, str]]:
    """``(consumer index, producer id, output name)`` for each ``steps.<id>.outputs.<name>``.

    The index is the position of the consuming step; a job ``outputs:`` entry
    sits after the last step.  Ids and names are casefolded.
    """
    scopes = _step_scopes(graph, job_id)
    scopes.append(_job_output_scope(graph, job_id))
    for index, expressions in enumerate(scopes):
        for body in expressions:
            for step_id, name in _STEP_OUTPUT_REF.findall(body):
                yield index, step_id.casefold(), name.casefold()


@register_rule("FLOW004")
def check_unused_outputs(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """An output is declared but never consumed downstream.

    Consumed means: matched by an input of a later step (by name, honouring
    ``bind:``), or read explicitly as ``steps.<id>.outputs.<name>`` (dot or
    bracket syntax; ids and names compared as GitHub does: ignoring case, but
    ``-`` and ``_`` differ) inside a ``${{ }}`` of a *later* step of the same
    job: its ``with:``, ``env:``, ``run:``, ``if:``, ``name:`` or other keys, or
    in a job ``outputs:`` entry (a job's other fields cannot read ``steps``).
    ``needs.`` references are not counted: only the compiler's own forwarding and
    the job ``outputs:`` the recipe declares make them resolve.
    """
    consumed: set[str] = set()  # normalized output names
    last_reader: dict[tuple[str, str, str], int] = {}  # (job, step, name) -> index
    for node in graph.nodes():
        for norm_name in node.input_specs:
            consumed.add(node.bind.get(norm_name, norm_name))

    for job_id in graph.job_ids():
        for index, step_id, name in _step_references(graph, job_id):
            key = (job_id, step_id, name)
            last_reader[key] = max(index, last_reader.get(key, -1))

    for job_id in graph.job_ids():
        for position, node in enumerate(graph.job_nodes(job_id)):
            for norm_name, spelling in node.output_spellings.items():
                key = (job_id, node.step_id.casefold(), spelling.casefold())
                if norm_name in consumed or last_reader.get(key, -1) > position:
                    continue
                yield Finding(
                    rule_id="FLOW004",
                    severity=Severity.INFO,
                    message=(
                        f"Output '{norm_name}' of '{node.key}' "
                        f"is not consumed by any downstream step."
                    ),
                    location=node.key,
                )


@register_rule("FLOW007")
def check_output_references(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """A ``steps.*.outputs.*`` or ``needs.*.outputs.*`` reference that resolves to nothing.

    * ``steps.<id>.outputs.<name>`` naming a step that does not run before the
      reader, or an output the step's action does not declare (``-`` and ``_``
      are different characters to GitHub).
    * ``needs.<job>.outputs.<name>`` naming a job that is not among the job's
      ``needs`` (explicit or inferred from data flow), or an output that job
      neither declares in ``outputs:`` nor has forwarded by the compiler.
    """
    if graph.recipe is None:
        return
    from reci.compiler import detect_cross_job_edges

    edges = detect_cross_job_edges(graph, config)
    seen: set[tuple[str, str]] = set()
    for finding in _output_reference_findings(graph, edges):
        if (finding.location, finding.message) not in seen:
            seen.add((finding.location, finding.message))
            yield finding


def _output_reference_findings(graph, edges) -> Iterable[Finding]:
    for job_id, job in graph.recipe.jobs.items():
        nodes = graph.job_nodes(job_id)
        by_id = {n.step_id.casefold(): (i, n) for i, n in enumerate(nodes)}
        step_scopes = _step_scopes(graph, job_id)
        scopes = [*step_scopes, _job_output_scope(graph, job_id)]
        for index, expressions in enumerate(scopes):
            location = nodes[index].key if index < len(nodes) else job_id
            for body in expressions:
                for step_id, name in _STEP_OUTPUT_REF.findall(body):
                    yield from _check_step_ref(by_id, index, location, step_id, name)

        needed = {n.casefold() for n in job.needs}
        needed |= {e.source_job.casefold() for e in edges if e.target_job == job_id}
        job_level = _expressions(
            job.runs_on,
            job.strategy,
            job.env,
            job.continue_on_error,
            job.extra,
            conditions=[job.if_],
        )
        everywhere = [*job_level, *(e for scope in step_scopes for e in scope)]
        for body in everywhere:
            for source, name in _NEEDS_OUTPUT_REF.findall(body):
                yield from _check_needs_ref(graph, edges, needed, job_id, source, name)


def _check_step_ref(by_id, index, location, step_id, name):
    found = by_id.get(step_id.casefold())
    read = f"'{location}' reads steps.{step_id}.outputs.{name}"
    if found is None:
        message = f"{read}, but the job has no step '{step_id}'."
    elif found[0] >= index:
        message = f"{read}, but step '{step_id}' has not run at that point."
    else:
        node = found[1]
        spellings = {s.casefold() for s in node.output_spellings.values()}
        spec = node.action_spec
        if spec is None or name.casefold() in spellings:
            return  # an undeclared run: output cannot be judged
        near = {normalize_name(s): s for s in node.output_spellings.values()}.get(
            normalize_name(name)
        )
        if near is None and not spec.composite:
            return  # a JavaScript/Docker action may set outputs it does not declare
        hint = f" (did you mean '{near}'?)" if near else ""
        message = f"{read}, but '{node.key}' declares no output '{name}'{hint}."
    yield Finding(
        rule_id="FLOW007",
        severity=Severity.WARNING,
        message=message,
        location=location,
    )


def _check_needs_ref(graph, edges, needed, job_id, source, name):
    if source.casefold() == "setup":
        return  # config: CONF004's
    job = next(
        (j for j in graph.recipe.jobs if j.casefold() == source.casefold()), None
    )
    read = f"Job '{job_id}' reads needs.{source}.outputs.{name}"
    if job is None or source.casefold() not in needed:
        message = f"{read}, but '{source}' is not a job it needs."
    else:
        declared = {
            str(k).casefold() for k in graph.recipe.jobs[job].extra.get("outputs", {})
        }
        forwarded = {e.source_output.casefold() for e in edges if e.source_job == job}
        if name.casefold() in declared | forwarded:
            return
        message = (
            f"{read}, but job '{job}' declares no such output and the compiler "
            f"forwards none by that name; it is empty."
        )
    yield Finding(
        rule_id="FLOW007",
        severity=Severity.WARNING,
        message=message,
        location=job_id,
        suggestion=(
            "Declare it under the producing job's outputs:, or pass the value "
            "through an input the compiler can wire."
        ),
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


#: A status function in an ``if:`` lets a job run although a job it needs was skipped.
_STATUS_FUNCTION_RE = re.compile(r"\b(always|cancelled|failure)\s*\(")


def _always_true(condition: str) -> bool:
    """An ``if:`` that never skips a job.

    >>> _always_true("always()"), _always_true("${{ true }}"), _always_true("x == 1")
    (True, True, False)
    """
    body = condition.strip()
    if body.startswith("${{") and body.endswith("}}"):
        body = body[3:-2].strip()
    return body in ("true", "always()")


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
        consumer = graph.recipe.jobs[edge.target_job]
        if (
            job.if_
            and not _always_true(job.if_)
            and not (consumer.if_ and _STATUS_FUNCTION_RE.search(consumer.if_))
            and (edge.source_job, edge.source_output, "if") not in reported
        ):
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
