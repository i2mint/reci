# reci.validation.rules.dag

DAG structure validation rules (DAG001–DAG004).

### Functions

| [`check_cycles`](#reci.validation.rules.dag.check_cycles)(graph, config)            | Detect cycles in the dependency graph.                                           |
|-----------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`check_duplicate_outputs`](#reci.validation.rules.dag.check_duplicate_outputs)(graph, config) | Flag duplicate output names within a job (at the job output level).              |
| [`check_isolated_nodes`](#reci.validation.rules.dag.check_isolated_nodes)(graph, config)    | Flag nodes with no data connections (no outputs consumed, no inputs from graph). |

### reci.validation.rules.dag.check_cycles(graph, config)

Detect cycles in the dependency graph.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]

### reci.validation.rules.dag.check_duplicate_outputs(graph, config)

Flag duplicate output names within a job (at the job output level).

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]

### reci.validation.rules.dag.check_isolated_nodes(graph, config)

Flag nodes with no data connections (no outputs consumed, no inputs from graph).

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]
