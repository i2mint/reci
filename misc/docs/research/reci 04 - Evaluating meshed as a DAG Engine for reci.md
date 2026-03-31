# Evaluating `meshed` as a DAG Engine for `reci`

**Author:** Thor Whalen  
**Date:** 2026-03-28

## Executive Summary

**`meshed.DAG` is a poor fit for `reci`'s core use case**, but **`meshed.itools` contains standalone graph utilities worth considering.** The `DAG` class fundamentally requires Python callables as nodes — it introspects function signatures via `inspect.signature` to auto-wire the graph — making it unable to represent CI action specs without invasive workarounds. Its single-output-per-node model, lack of serialization, and absence of conditional execution compound the mismatch. However, `meshed.itools` exposes a clean `topological_sort` function and graph primitives (`edges`, `nodes`, `isolated_nodes`) that operate on plain adjacency `Mapping` objects, independent of the `FuncNode`/`DAG` machinery.

For a CI recipe compiler that constructs but never executes DAGs, the recommended path is either:

- **Use `meshed.itools` selectively** — for `topological_sort`, `edges`, `nodes` — paired with a custom `RecipeGraph` class, or
- **Use `graphlib.TopologicalSorter` (stdlib)** for zero-dependency topological sorting with built-in cycle detection and parallel-wave scheduling.

---

## Part I: API Fit

### 1. Can `meshed.DAG` represent non-callable nodes?

**No — not without invasive workarounds.** `meshed.DAG` accepts an iterable of callables or `FuncNode` instances, and `FuncNode` wraps a real Python function [1]:

```python
FuncNode(func=f, out="a_plus_b", bind={"d": "b"}, name="f")
```

The `func` parameter must be a callable whose signature can be introspected via `i2.signatures.Sig` (a subclass of `inspect.Signature`). The DAG auto-wires nodes by matching function parameter names to output variable names — `combine(this, that)` automatically connects to the outputs of functions named `this` and `that` [1]. This is elegant for composing Python functions but **fundamentally incompatible with nodes that are CI action specs** carrying metadata like `i2mint/wads/actions/run-tests@master`, step IDs, and job groupings.

You could theoretically create dummy Python functions for each action whose signatures mirror the action's declared inputs and outputs, but this creates an absurd indirection layer: writing `def run_tests(python_version, coverage_flag): pass` solely to satisfy meshed's signature introspection, then immediately discarding the callable. The abstraction adds cost without value.

### 2. Does `FuncNode` support input renaming?

**Yes, through `bind` and `out`.** If action A outputs `new_version` but action B expects `tag_name`, you create `FuncNode(func=action_a_stub, out="tag_name")` or `FuncNode(func=action_b_stub, bind={"tag_name": "new_version"})`. The `bind` dict maps `{original_param_name: dag_variable_name}`, and `out` specifies the output variable name [1]. This mechanism is flexible — but requires callable stubs to use.

### 3. How to handle multiple outputs per node?

**meshed DAGs have a single `out` string per node.** CI actions routinely produce multiple outputs (e.g., `build` emitting both `artifact-path` and `build-number`). Workarounds:

- **Wrapper returning a dict**: the node returns `{"artifact_path": ..., "build_number": ...}` and downstream nodes unpack it. Ugly — requires downstream nodes to know the dict structure.
- **Multiple `FuncNode` wrappers per action**: one per output. Cleaner wiring, but multiplies the number of nodes and misrepresents the actual computation graph.

Neither is clean. This is a real impedance mismatch.

### 4. How does meshed handle external inputs?

**Naturally.** Root inputs are variables that appear as function parameters but aren't produced by any node. They become the DAG's synthesized `__signature__` and are passed as kwargs at call time: `dag(x=1, a=2, b=1)` [1]. This design maps well to config injection from `pyproject.toml`, though `reci` wouldn't actually *call* the DAG.

### 5. Can meshed produce a topological ordering?

**Yes.** `meshed.itools` provides a standalone `topological_sort` function, importable from the `meshed` root [1]:

```python
from meshed import topological_sort
# or: from meshed.itools import topological_sort

g = {
    0: [4, 2],
    4: [3, 1],
    2: [3],
    3: [1]
}
list(topological_sort(g))  # [0, 4, 2, 3, 1]
```

This is a DFS-based implementation operating on adjacency `Mapping` objects (the `Graph` type alias). It uses a recursive helper with a visited set and stack insertion. **Importantly, this function is independent of the `DAG`/`FuncNode` machinery** — it works on plain `dict` graphs. The DAG class also uses topological ordering internally for `synopsis_string()` and `__call__` execution [1].

**Limitation:** This `topological_sort` does **not** include cycle detection. The recursive helper tracks visited nodes to avoid revisiting, but does not distinguish between "in current path" and "fully processed" nodes — so it will silently produce incorrect output on cyclic graphs rather than raising an error. Compare with `graphlib.TopologicalSorter`, which raises `CycleError` with the cycle path [4].

---

## Part II: What to Extract vs. Depend On

### 6. Dependency footprint

meshed depends on `i2`, the i2mint package for signature manipulation [2, 3]. The `i2` package is pure Python with no mandatory external dependencies — its `Sig` class extends `inspect.Signature` with merging, renaming, and transformation capabilities [3]. The full transitive chain:

| Package | Install size | Mandatory deps |
|---------|-------------|----------------|
| meshed  | ~100–300 KB | `i2`           |
| i2      | ~200–500 KB | stdlib only    |
| **Total** | **~300–800 KB** | **1 package** |

Graphviz is an optional dependency for `dot_digraph()`. No heavy dependencies (no numpy, pandas, scipy). MIT-licensed, pure Python (`py3-none-any` wheel), at version **0.1.161** [1, 2].

### 7. Which classes/functions would `reci` use?

If taking meshed as a dependency, the useful surface is surprisingly narrow:

**From `meshed.itools` (graph utilities on plain `Mapping` objects):**
- `topological_sort(g)` — DFS topological ordering
- `edges(graph)` — yield `(parent, child)` tuples
- `nodes(graph)` — yield all nodes
- `isolated_nodes(graph)` — yield nodes with no edges

**From `meshed.makers`:**
- `edge_reversed_graph(g)` — flip edge directions

**From `meshed.dag` — probably NOT:**
- `DAG` — requires callables, wrong abstraction for reci
- `FuncNode` — same issue
- `dot_digraph()` — useful for visualization but tied to the DAG class

The useful parts are all in `itools` and operate on plain adjacency dicts, not on `DAG`/`FuncNode`. This raises the question: is the dependency justified for ~5 utility functions on dicts?

### 8. Minimal code surface if extracting

If vendoring instead of depending:

| Component | Lines | Notes |
|-----------|-------|-------|
| `topological_sort` | ~30 | DFS recursive, from `itools.py` |
| `edges`, `nodes`, `isolated_nodes` | ~30 | Trivial graph traversals |
| `edge_reversed_graph` | ~15 | From `makers.py` |
| Node representation | ~40 | A frozen dataclass replacing `FuncNode` |
| DAG construction + validation | ~100–200 | Adjacency building, root input detection |
| Cycle detection | ~30 | Not in meshed — must be written fresh |
| **Total** | **~250–350** | Much less than meshed's full codebase |

The `dag.py` module itself deeply depends on `i2.signatures.Sig` for signature introspection. Extracting the `DAG` class without `i2` means rewriting the entire wiring logic — at which point you're writing a new DAG library, not extracting meshed.

---

## Part III: Gaps

### 9. What does meshed NOT provide that `reci` needs?

**YAML serialization:** meshed has no serialization layer. Converting a DAG to GitHub Actions workflow YAML requires a complete custom serializer that understands job/step structure, `uses:` references, `with:` input mappings, and `outputs:` declarations.

**Conditional node execution:** meshed executes every node on every call — no skip conditions, `if:` expressions, or branch routing. GitHub Actions supports `if:` conditions on steps and jobs. `reci` must implement this entirely.

**Cross-job boundaries:** GitHub Actions has a two-level hierarchy (jobs containing steps) with different data-passing semantics (step outputs vs. job outputs vs. artifacts). meshed's flat bipartite graph has no concept of grouping nodes into containers. This is a fundamental modeling gap — likely requiring a two-level DAG: an outer job-dependency DAG and inner step-ordering within each job.

**Cycle detection with human-readable errors:** meshed's `topological_sort` does not detect cycles — it silently produces incorrect output. `reci` needs clear error messages like _"Action 'deploy' depends on 'test' which depends on 'deploy' — circular dependency detected."_

**DAG visualization for debugging:** meshed *does* provide `dot_digraph()` via Graphviz [1], which is its strongest feature. However, it visualizes the internal bipartite representation (with `_` suffixed func-nodes), not a clean action-dependency view. For `reci`, a simpler action-to-action diagram would be more useful.

### 10. Alternative libraries

| Feature | graphlib (stdlib) | NetworkX | meshed.itools | meshed.DAG | Dask/Prefect/Hamilton |
|---------|:-:|:-:|:-:|:-:|:-:|
| Non-callable nodes | ✅ | ✅ | ✅ | ❌ | ❌ |
| Topological sort | ✅ | ✅ | ✅ | implicit | internal only |
| Cycle detection | ✅ `CycleError` | ✅ `find_cycle` | ❌ | undocumented | N/A |
| Parallel-wave scheduling | ✅ `get_ready/done` | ✅ `topological_generations` | ❌ | ❌ | N/A |
| Node/edge metadata | ❌ | ✅ rich dicts | ❌ | only via FuncNode | ❌ |
| Graph introspection | ❌ | ✅ full API | basic (`edges`/`nodes`) | partial | ❌ |
| Serialization | ❌ | ✅ JSON | ❌ | ❌ | ❌ |
| Visualization | ❌ | ✅ multiple | ❌ | ✅ Graphviz | ❌ |
| Install size | **0 (stdlib)** | ~2.1 MB | ~300–800 KB | same | 10–100+ MB |
| Mandatory deps | **0** | **0** | 1 (`i2`) | same | 7–20+ |

**`graphlib.TopologicalSorter` (Python 3.9+)** is the strongest foundation [4]. Nodes can be any hashable object — frozen dataclasses, strings, named tuples — so `reci` can use `@dataclass(frozen=True) class ActionSpec` directly as graph nodes. The `prepare()`/`get_ready()`/`done()` protocol yields parallelizable "waves" that map to GitHub Actions job parallelism. `CycleError` reports one cycle with the exact node path [4]. Zero dependencies, ~250 lines of stdlib code.

The limitation: graphlib provides no graph introspection (no predecessors/successors queries) and no edge metadata [4]. `reci` would maintain a parallel adjacency structure.

**NetworkX** is the upgrade path if `reci` needs subgraph extraction, ancestor/descendant queries, or critical-path analysis [5]. Pure Python, zero mandatory dependencies, rich node/edge attribute dicts. `find_cycle()` returns the full cycle as edge tuples. `topological_generations()` directly produces parallel wave structure. The ~2.1 MB install size is the main cost, though 95% goes unused.

**`meshed.itools`** occupies a middle ground: it provides `topological_sort`, `edges`, `nodes`, and `isolated_nodes` operating on plain adjacency `Mapping` objects. It's lighter than NetworkX and more Pythonic than raw `graphlib`. But it lacks cycle detection, parallel-wave scheduling, and graph introspection beyond the basics. For `reci`, the missing cycle detection is a dealbreaker unless supplemented.

**Dask, Prefect, and Hamilton are definitively wrong** for this use case [6]. All three are execution-oriented frameworks requiring Python callables as nodes. Prefect alone pulls 20+ direct dependencies. Hamilton's "functions-as-nodes" paradigm is elegant for data pipelines but architecturally mismatched with CI action specs. None provides value over graphlib for a non-execution DAG compiler.

---

## Recommendation

The dependency decision reduces to three viable paths:

### Path A: `graphlib` + custom `RecipeGraph` (recommended)

Zero new dependencies. Build a ~200-line `RecipeGraph` class wrapping `graphlib.TopologicalSorter` with:

```python
@dataclass(frozen=True)
class ActionSpec:
    ref: str          # "i2mint/wads/actions/run-tests@master"
    step_id: str
    job: str
    inputs: dict
    outputs: list[str]

class RecipeGraph:
    _deps: dict[ActionSpec, set[ActionSpec]]  # graphlib format
    _edges: dict[tuple[str, str], str]        # (src_output, dst_input) metadata

    def execution_waves(self):
        ts = TopologicalSorter(self._deps)
        ts.prepare()
        waves = []
        while ts.is_active():
            wave = ts.get_ready()
            waves.append(wave)
            ts.done(*wave)
        return waves  # each wave = one parallel job layer
```

Built-in `CycleError` handles cycle detection. The `get_ready()`/`done()` protocol naturally maps to GitHub Actions job parallelism.

### Path B: `meshed.itools` + custom cycle detection

Use `topological_sort`, `edges`, `nodes` from `meshed.itools` for graph operations on adjacency dicts. Add custom cycle detection (~30 lines of DFS with back-edge tracking). This keeps the i2mint ecosystem in play and uses familiar conventions, but adds a dependency for functions that are individually trivial.

### Path C: NetworkX (if complexity grows)

Graduate to NetworkX only if `reci` later needs subgraph visualization, transitive reduction, or ancestor queries. Migration from Path A is low-cost because NetworkX's `DiGraph` is a superset of the adjacency-dict interface.

**Do not use `meshed.DAG`** — its callable-node requirement creates an impedance mismatch that would require dummy function stubs for every CI action. The `DAG` class's strengths (auto-wiring from signatures, scope propagation, sub-DAG slicing) are all execution-oriented features that `reci` doesn't need.

### Key components `reci` should build regardless of DAG choice

- A frozen `ActionSpec` dataclass — node identity and metadata
- A `RecipeGraph` class — adjacency structure, validation, wave computation
- A `YAMLCompiler` — traverses the graph and emits GitHub Actions workflow YAML
- Cycle detection with human-readable error messages
- Two-level DAG modeling (jobs containing steps)
- Conditional execution predicates (`if:` expressions)

---

## References

[1] i2mint, "meshed: Link functions up into callable objects," GitHub repository, [meshed](https://github.com/i2mint/meshed)

[2] i2mint, "meshed," Python Package Index, [meshed · PyPI](https://pypi.org/project/meshed/)

[3] i2mint, "i2: Python Mint creation, manipulation, and use," GitHub repository, [i2](https://github.com/i2mint/i2)

[4] Python Software Foundation, "graphlib — Functionality to operate with graph-like structures," Python 3 documentation, [graphlib](https://docs.python.org/3/library/graphlib.html)

[5] NetworkX Developers, "NetworkX: Network Analysis in Python," [networkx](https://github.com/networkx/networkx)

[6] Dask Development Team, "Dask Delayed," Dask documentation, [dask.delayed](https://docs.dask.org/en/stable/delayed.html)
