"""Compiler — recipe + action specs + config → GitHub Actions workflow YAML.

The compiler resolves data-flow wiring using a five-level precedence, injects
a ``setup`` job that exports config values as job outputs, auto-generates the
cross-job output forwarding ceremony, and adds ``needs:`` edges from data-flow
dependencies.
"""

from __future__ import annotations

import json
import re
from typing import Any

from reci.action_spec import ActionSpec, normalize_name, action_local_name
from reci.recipe import Recipe, StepSpec, JobSpec
from reci.graph import RecipeGraph, ActionNode, CrossJobEdge

# ---------------------------------------------------------------------------
# Config reference rewriting
# ---------------------------------------------------------------------------

_CONFIG_REF_RE = re.compile(r'\$\{\{\s*config\.(\w+)\s*\}\}')


def _rewrite_config_refs(value: str) -> str:
    r"""Replace ``${{ config.X }}`` with ``${{ needs.setup.outputs.X }}``.

    >>> _rewrite_config_refs('${{ config.python_versions }}')
    '${{ needs.setup.outputs.python_versions }}'
    """
    return _CONFIG_REF_RE.sub(r'${{ needs.setup.outputs.\1 }}', value)


def _rewrite_all_config_refs(obj: Any) -> Any:
    """Recursively rewrite config references in strings, dicts, and lists."""
    if isinstance(obj, str):
        return _rewrite_config_refs(obj)
    if isinstance(obj, dict):
        return {k: _rewrite_all_config_refs(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rewrite_all_config_refs(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# Setup job generation
# ---------------------------------------------------------------------------


def _serialize_config_value(value: Any) -> str:
    """Serialize a config value for GITHUB_OUTPUT."""
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def _build_setup_job(config: dict[str, Any]) -> dict:
    """Generate the setup job that exports config values as job outputs."""
    lines: list[str] = []
    outputs: dict[str, str] = {}

    for key, value in config.items():
        serialized = _serialize_config_value(value)
        lines.append(f'echo "{key}={serialized}" >> $GITHUB_OUTPUT')
        outputs[key] = f'${{{{ steps.config.outputs.{key} }}}}'

    run_script = '\n'.join(lines) if lines else 'echo "No config values"'

    return {
        'name': 'Setup',
        'runs-on': 'ubuntu-latest',
        'outputs': outputs,
        'steps': [
            {
                'name': 'Export config',
                'id': 'config',
                'run': run_script,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Step building
# ---------------------------------------------------------------------------


def _build_step(step: StepSpec, *, action_spec: ActionSpec | None = None) -> dict:
    """Convert a StepSpec to a GitHub Actions step dict.

    In Phase 1 this passes through ``with:`` values verbatim (after
    config ref rewriting).  Auto-wiring is layered on in Phase 2.
    """
    d: dict[str, Any] = {}
    if step.name:
        d['name'] = step.name
    d['id'] = step.id

    if step.uses:
        d['uses'] = step.uses
    if step.run:
        d['run'] = _rewrite_config_refs(step.run)
    if step.if_:
        d['if'] = _rewrite_config_refs(step.if_)
    if step.with_:
        d['with'] = {k: _rewrite_config_refs(v) for k, v in step.with_.items()}
    if step.env:
        d['env'] = {k: _rewrite_config_refs(v) for k, v in step.env.items()}

    return d


# ---------------------------------------------------------------------------
# Job building
# ---------------------------------------------------------------------------


def _build_job(
    job_spec: JobSpec,
    *,
    action_specs: dict[str, ActionSpec],
    config: dict[str, Any],
    graph: RecipeGraph,
    cross_job_edges: list[CrossJobEdge] | None = None,
    wired_inputs: dict[str, dict[str, str]] | None = None,
) -> dict:
    """Convert a JobSpec to a GitHub Actions job dict."""
    d: dict[str, Any] = {}

    if job_spec.if_:
        d['if'] = _rewrite_config_refs(job_spec.if_)
    d['runs-on'] = job_spec.runs_on

    # needs: explicit + setup + data-flow driven
    needs = list(job_spec.needs)
    if 'setup' not in needs:
        needs.insert(0, 'setup')
    # Add cross-job needs
    if cross_job_edges:
        for edge in cross_job_edges:
            if edge.target_job == job_spec.id and edge.source_job not in needs:
                needs.append(edge.source_job)
    d['needs'] = needs

    if job_spec.strategy:
        d['strategy'] = _rewrite_all_config_refs(job_spec.strategy)
    if job_spec.permissions:
        d['permissions'] = job_spec.permissions
    if job_spec.continue_on_error:
        d['continue-on-error'] = True
    if job_spec.env:
        d['env'] = {k: _rewrite_config_refs(v) for k, v in job_spec.env.items()}

    # Job-level outputs for cross-job forwarding
    if cross_job_edges:
        job_outputs = _build_job_outputs(
            job_spec.id, graph.job_nodes(job_spec.id), cross_job_edges
        )
        if job_outputs:
            d['outputs'] = job_outputs

    # Steps
    steps: list[dict] = []
    for step_spec in job_spec.steps:
        spec = action_specs.get(step_spec.uses) if step_spec.uses else None
        step_dict = _build_step(step_spec, action_spec=spec)

        # Apply wired inputs (from Phase 2+)
        node_key = f'{job_spec.id}.{step_spec.id}'
        if wired_inputs and node_key in wired_inputs:
            wired = wired_inputs[node_key]
            existing_with = step_dict.get('with', {})
            # Wired inputs fill in gaps; explicit with: takes precedence
            merged = {**wired, **existing_with}
            if merged:
                step_dict['with'] = merged

        steps.append(step_dict)

    d['steps'] = steps
    return d


# ---------------------------------------------------------------------------
# Cross-job output forwarding (Phase 5)
# ---------------------------------------------------------------------------


def _build_job_outputs(
    job_id: str,
    nodes: list[ActionNode],
    cross_job_edges: list[CrossJobEdge],
) -> dict[str, str]:
    """Auto-generate job-level outputs for cross-job consumption."""
    outputs: dict[str, str] = {}
    for edge in cross_job_edges:
        if edge.source_job == job_id:
            output_key = edge.source_output
            outputs[output_key] = (
                f'${{{{ steps.{edge.source_step_id}.outputs.{edge.source_output} }}}}'
            )
    return outputs


# ---------------------------------------------------------------------------
# Data-flow wiring (Phase 2)
# ---------------------------------------------------------------------------


def _resolve_config_key(
    input_name: str,
    ref: str | None,
    config: dict[str, Any],
) -> str | None:
    """Find a config key for an action input.

    Checks scoped ``action_local_name__input_name`` first, then shared
    ``input_name``.  Returns the config key name or ``None``.
    """
    if ref:
        local = action_local_name(ref)
        scoped = f'{local}__{input_name}'
        if scoped in config:
            return scoped
    if input_name in config:
        return input_name
    return None


def _wire_step_inputs(
    node: ActionNode,
    *,
    upstream_outputs: dict[str, tuple[str, str]],
    config: dict[str, Any],
) -> dict[str, str]:
    """Resolve each input using the five-level precedence.

    Returns a dict of ``{original_input_name: expression}`` for the ``with:``
    block.  Only includes inputs that need wiring (levels 2 and 3); level 1
    (explicit) is handled by the recipe's ``with_:``, and level 4 (defaults)
    means we omit.

    *upstream_outputs*: ``{normalized_output_name: (step_id, original_output_name)}``
    """
    wired: dict[str, str] = {}
    specs = node.input_specs

    for norm_name, input_spec in specs.items():
        # Level 1: explicit with: — already in the recipe, skip
        if norm_name in {normalize_name(k) for k in node.with_}:
            continue

        # Check bind mapping: if input is renamed, search for the bind target
        search_name = node.bind.get(norm_name, norm_name)

        # Level 2: upstream output name match
        if search_name in upstream_outputs:
            step_id, out_name = upstream_outputs[search_name]
            wired[input_spec.name] = f'${{{{ steps.{step_id}.outputs.{out_name} }}}}'
            continue

        # Level 3: config (scoped then shared)
        config_key = _resolve_config_key(norm_name, node.ref, config)
        if config_key is not None:
            wired[input_spec.name] = (
                f'${{{{ needs.setup.outputs.{config_key} }}}}'
            )
            continue

        # Level 4: default exists → omit (GitHub Actions uses the default)
        # Level 5: required + no source → skip here, caught by validation

    return wired


def _build_upstream_outputs(
    graph: RecipeGraph,
    job_id: str,
    *,
    up_to_key: str,
) -> dict[str, tuple[str, str]]:
    """Collect all output names from steps preceding *up_to_key* in the same job.

    Returns ``{normalized_name: (step_id, normalized_name)}``.
    Nearest predecessor wins (later entries overwrite earlier).
    """
    outputs: dict[str, tuple[str, str]] = {}
    for node in graph.job_nodes(job_id):
        if node.key == up_to_key:
            break
        for name in node.output_names:
            outputs[name] = (node.step_id, name)
    return outputs


# ---------------------------------------------------------------------------
# Cross-job edge detection (Phase 5)
# ---------------------------------------------------------------------------


def _detect_cross_job_edges(
    graph: RecipeGraph,
    config: dict[str, Any],
) -> list[CrossJobEdge]:
    """Find data-flow edges between steps in different jobs."""
    edges: list[CrossJobEdge] = []

    # Build a map of all outputs per job
    job_outputs: dict[str, dict[str, tuple[str, str]]] = {}
    for job_id in graph.job_ids():
        outs: dict[str, tuple[str, str]] = {}
        for node in graph.job_nodes(job_id):
            for name in node.output_names:
                outs[name] = (node.step_id, name)
        job_outputs[job_id] = outs

    for job_id in graph.job_ids():
        for node in graph.job_nodes(job_id):
            for norm_name, input_spec in node.input_specs.items():
                # Skip if already wired explicitly or from intra-job output
                if norm_name in {normalize_name(k) for k in node.with_}:
                    continue
                search_name = node.bind.get(norm_name, norm_name)

                # Check intra-job first
                intra = _build_upstream_outputs(graph, job_id, up_to_key=node.key)
                if search_name in intra:
                    continue

                # Check config
                if _resolve_config_key(norm_name, node.ref, config) is not None:
                    continue

                # Search other jobs
                for other_job_id, other_outs in job_outputs.items():
                    if other_job_id == job_id:
                        continue
                    if search_name in other_outs:
                        src_step_id, src_output = other_outs[search_name]
                        edges.append(
                            CrossJobEdge(
                                source_job=other_job_id,
                                source_step_id=src_step_id,
                                source_output=src_output,
                                target_job=job_id,
                                target_step_id=node.step_id,
                                target_input=norm_name,
                            )
                        )
                        break  # first match wins

    return edges


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


class CompilationError(Exception):
    """Raised when compilation fails."""


def compile_recipe(
    recipe: Recipe,
    action_specs: dict[str, ActionSpec],
    *,
    config: dict[str, Any] | None = None,
) -> dict:
    """Compile a recipe into a GitHub Actions workflow dict.

    Parameters
    ----------
    recipe:
        Parsed recipe.
    action_specs:
        Action specs keyed by ref string.
    config:
        Flat config dict (optional).  If provided, a ``setup`` job is
        injected and config references are wired.
    """
    config = config or {}
    graph = RecipeGraph.from_recipe(recipe, action_specs)

    # Detect cross-job edges
    cross_job_edges = _detect_cross_job_edges(graph, config) if config else []

    # Compute wired inputs for all nodes
    all_wired: dict[str, dict[str, str]] = {}
    for job_id in graph.job_ids():
        for node in graph.job_nodes(job_id):
            upstream = _build_upstream_outputs(graph, job_id, up_to_key=node.key)

            # Add cross-job sources
            for edge in cross_job_edges:
                if edge.target_job == job_id and edge.target_step_id == node.step_id:
                    upstream[edge.source_output] = (
                        f'needs.{edge.source_job}.outputs',
                        edge.source_output,
                    )

            wired = _wire_step_inputs(
                node,
                upstream_outputs=upstream,
                config=config,
            )
            if wired:
                all_wired[node.key] = wired

    # Build workflow
    workflow: dict[str, Any] = {}
    workflow['name'] = recipe.name or 'CI'
    workflow['on'] = recipe.on

    if recipe.env:
        workflow['env'] = recipe.env

    jobs: dict[str, Any] = {}

    # Setup job (always present when config is provided)
    if config:
        jobs['setup'] = _build_setup_job(config)

    # Recipe jobs
    for job_id, job_spec in recipe.jobs.items():
        jobs[job_id] = _build_job(
            job_spec,
            action_specs=action_specs,
            config=config,
            graph=graph,
            cross_job_edges=cross_job_edges,
            wired_inputs=all_wired,
        )

    workflow['jobs'] = jobs
    return workflow
