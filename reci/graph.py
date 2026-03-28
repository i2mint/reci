"""Recipe DAG — computational graph built on :mod:`graphlib`.

:class:`RecipeGraph` wraps :class:`graphlib.TopologicalSorter` to model
the two-level structure of GitHub Actions workflows: jobs containing
sequential steps, with inter-job parallelism governed by ``needs:``
edges and data-flow dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from graphlib import TopologicalSorter, CycleError
from typing import Any, Iterable

from reci.action_spec import ActionSpec, InputSpec, normalize_name
from reci.recipe import Recipe, StepSpec, JobSpec


# ---------------------------------------------------------------------------
# Node representation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActionNode:
    """A single step in the recipe graph.

    Uses ``step_id`` + ``job`` as its identity (the graph keys these as
    ``"{job}.{step_id}"`` strings for :class:`TopologicalSorter`).
    """

    step_id: str
    job: str
    ref: str | None = None
    action_spec: ActionSpec | None = None
    with_: dict[str, str] = field(default_factory=dict, hash=False, compare=False)
    bind: dict[str, str] = field(default_factory=dict, hash=False, compare=False)
    if_: str | None = field(default=None, hash=False, compare=False)
    declared_outputs: list[str] = field(
        default_factory=list, hash=False, compare=False
    )
    run: str | None = field(default=None, hash=False, compare=False)
    name: str | None = field(default=None, hash=False, compare=False)
    env: dict[str, str] = field(default_factory=dict, hash=False, compare=False)

    @property
    def key(self) -> str:
        return f'{self.job}.{self.step_id}'

    @property
    def output_names(self) -> list[str]:
        """All normalized output names this node produces."""
        names: list[str] = list(self.declared_outputs)
        if self.action_spec:
            for n in self.action_spec.outputs:
                if n not in names:
                    names.append(n)
        return names

    @property
    def input_specs(self) -> dict[str, InputSpec]:
        """Input specs from the action, or empty for run: steps."""
        if self.action_spec:
            return dict(self.action_spec.inputs)
        return {}


# ---------------------------------------------------------------------------
# Cross-job edge (Phase 5 placeholder populated by compiler)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossJobEdge:
    """Data-flow edge between steps in different jobs."""

    source_job: str
    source_step_id: str
    source_output: str
    target_job: str
    target_step_id: str
    target_input: str


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------


class RecipeGraph:
    """The computational DAG of a recipe.

    Nodes are identified by ``"{job}.{step_id}"`` strings.  The actual
    :class:`ActionNode` objects are stored in :attr:`_nodes`.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, ActionNode] = {}
        self._deps: dict[str, set[str]] = {}  # key -> set of predecessor keys
        self._jobs: dict[str, list[str]] = {}  # job_id -> ordered node keys

    # -- construction -------------------------------------------------------

    def add_node(self, node: ActionNode, *, depends_on: Iterable[str] = ()) -> None:
        key = node.key
        self._nodes[key] = node
        self._deps.setdefault(key, set()).update(depends_on)
        self._jobs.setdefault(node.job, []).append(key)

    @classmethod
    def from_recipe(
        cls,
        recipe: Recipe,
        action_specs: dict[str, ActionSpec],
    ) -> RecipeGraph:
        """Build a graph from a parsed recipe and fetched action specs.

        *action_specs* is keyed by action ref (e.g. ``"actions/checkout@v4"``).
        """
        graph = cls()

        for job_id, job in recipe.jobs.items():
            prev_key: str | None = None
            for step in job.steps:
                spec = action_specs.get(step.uses) if step.uses else None
                node = ActionNode(
                    step_id=step.id,
                    job=job_id,
                    ref=step.uses,
                    action_spec=spec,
                    with_=dict(step.with_),
                    bind=dict(step.bind),
                    if_=step.if_,
                    declared_outputs=list(step.outputs),
                    run=step.run,
                    name=step.name,
                    env=dict(step.env),
                )
                # Within a job, steps are sequential
                deps: set[str] = set()
                if prev_key is not None:
                    deps.add(prev_key)
                graph.add_node(node, depends_on=deps)
                prev_key = node.key

        # Inter-job edges from explicit needs:
        for job_id, job in recipe.jobs.items():
            if not job.needs:
                continue
            first_key = graph._jobs.get(job_id, [None])[0]
            if first_key is None:
                continue
            for needed_job in job.needs:
                last_keys = graph._jobs.get(needed_job, [])
                if last_keys:
                    graph._deps.setdefault(first_key, set()).add(last_keys[-1])

        return graph

    # -- queries ------------------------------------------------------------

    def __getitem__(self, key: str) -> ActionNode:
        return self._nodes[key]

    def nodes(self) -> Iterable[ActionNode]:
        return self._nodes.values()

    def node_keys(self) -> Iterable[str]:
        return self._nodes.keys()

    def jobs(self) -> dict[str, list[ActionNode]]:
        return {
            jid: [self._nodes[k] for k in keys]
            for jid, keys in self._jobs.items()
        }

    def job_ids(self) -> list[str]:
        return list(self._jobs.keys())

    def job_nodes(self, job_id: str) -> list[ActionNode]:
        return [self._nodes[k] for k in self._jobs.get(job_id, [])]

    def predecessors(self, key: str) -> set[str]:
        return set(self._deps.get(key, ()))

    def execution_waves(self) -> list[tuple[str, ...]]:
        """Return parallel execution waves (topological generations).

        Each wave is a tuple of node keys that can execute concurrently.
        Raises :class:`CycleError` if the graph has cycles.
        """
        ts = TopologicalSorter(self._deps)
        ts.prepare()
        waves: list[tuple[str, ...]] = []
        while ts.is_active():
            wave = ts.get_ready()
            waves.append(tuple(wave))
            ts.done(*wave)
        return waves

    def validate(self, config: dict[str, Any] | None = None):
        """Run all validation rules and return a ValidationReport.

        Imported lazily to avoid circular imports (validation depends on graph).
        """
        from reci.validation.rules import run_all_rules

        return run_all_rules(self, config or {})
