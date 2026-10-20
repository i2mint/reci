# reci.graph

Recipe DAG — computational graph built on [`graphlib`](https://docs.python.org/3/library/graphlib.html#module-graphlib).

[`RecipeGraph`](#reci.graph.RecipeGraph) wraps [`graphlib.TopologicalSorter`](https://docs.python.org/3/library/graphlib.html#graphlib.TopologicalSorter) to model
the two-level structure of GitHub Actions workflows: jobs containing
sequential steps, with inter-job parallelism governed by `needs:`
edges and data-flow dependencies.

### Functions

| [`find_cycle`](#reci.graph.find_cycle)(deps)   | A dependency cycle in `{node: nodes it depends on}`, or `None`.   |
|---------------------------------------------------------------------|-------------------------------------------------------------------|

### Classes

| [`ActionNode`](#reci.graph.ActionNode)(step_id, job[, ref, action_spec, ...])   | A single step in the recipe graph.              |
|------------------------------------------------------------------------------------------------------|-------------------------------------------------|
| [`CrossJobEdge`](#reci.graph.CrossJobEdge)(source_job, source_step_id, ...)       | Data-flow edge between steps in different jobs. |
| [`RecipeGraph`](#reci.graph.RecipeGraph)()                                       | The computational DAG of a recipe.              |

### *class* reci.graph.ActionNode(step_id, job, ref=None, action_spec=None, with_=dict(), bind=dict(), if_=None, declared_outputs=list(), run=None, name=None, env=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A single step in the recipe graph.

Uses `step_id` + `job` as its identity (the graph keys these as
`"{job}.{step_id}"` strings for `TopologicalSorter`).

#### *property* input_specs *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [InputSpec](reci.action_spec.html.md#reci.action_spec.InputSpec)]*

steps.

* **Type:**
  Input specs from the action, or empty for run

#### *property* output_names *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]*

All normalized output names this node produces.

#### *property* output_spellings *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]*

`{normalized output name: spelling to emit}` for this node.

Declared (recipe) outputs come first; the action’s own `action.yml`
spelling wins when both name the same output.

### *class* reci.graph.CrossJobEdge(source_job, source_step_id, source_output, target_job, target_step_id, target_input, alternatives=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Data-flow edge between steps in different jobs.

#### alternatives *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ()*

other jobs that also produce the output; the first producer in recipe
order (`source_job`) is the one used

### *class* reci.graph.RecipeGraph

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The computational DAG of a recipe.

Nodes are identified by `"{job}.{step_id}"` strings.  The actual
[`ActionNode`](#reci.graph.ActionNode) objects are stored in `_nodes`.

#### execution_waves()

Return parallel execution waves (topological generations).

Each wave is a tuple of node keys that can execute concurrently.
Raises `CycleError` if the graph has cycles.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]]

#### *classmethod* from_recipe(recipe, action_specs)

Build a graph from a parsed recipe and fetched action specs.

*action_specs* is keyed by action ref (e.g. `"actions/checkout@v4"`).

* **Return type:**
  [`RecipeGraph`](#reci.graph.RecipeGraph)

#### job_needs(job_id)

The job ids *job_id* lists in its explicit `needs:`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### upstream_output_names(node, , other_jobs=True)

Normalized output names *node* can be fed from.

Outputs of earlier steps in its own job, plus (unless *other_jobs* is
false) outputs of any step in another job, which the compiler forwards
through `needs`.

* **Return type:**
  [`set`](https://docs.python.org/3/builtins/stdtypes.html#set)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### validate(config=None)

Run all validation rules and return a ValidationReport.

Imported lazily to avoid circular imports (validation depends on graph).

### reci.graph.find_cycle(deps)

A dependency cycle in `{node: nodes it depends on}`, or `None`.

The cycle is returned as a closed path following the dependency direction:
each node depends on the next, and the first node is repeated at the end.

```pycon
>>> find_cycle({'a': ['b'], 'b': ['a']})
['a', 'b', 'a']
>>> find_cycle({'a': ['b'], 'b': ['c'], 'c': ['a']})
['a', 'b', 'c', 'a']
>>> find_cycle({'a': ['b'], 'b': []}) is None
True
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)
