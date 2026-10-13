# reci.validation.rules.dag

DAG structure validation rules (DAG001–DAG004).

### Functions

| [`check_cycles`](#reci.validation.rules.dag.check_cycles)(graph, config)                 | Detect cycles in the dependency graph.                                           |
|----------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`check_data_flow_needs_cycles`](#reci.validation.rules.dag.check_data_flow_needs_cycles)(graph, config) | Data flow between jobs must not make their `needs` form a cycle.                 |
| [`check_duplicate_outputs`](#reci.validation.rules.dag.check_duplicate_outputs)(graph, config)      | Flag duplicate output names within a job (at the job output level).              |
| [`check_isolated_nodes`](#reci.validation.rules.dag.check_isolated_nodes)(graph, config)         | Flag nodes with no data connections (no outputs consumed, no inputs from graph). |

### reci.validation.rules.dag.check_cycles(graph, config)

Detect cycles in the dependency graph.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]

### reci.validation.rules.dag.check_data_flow_needs_cycles(graph, config)

Data flow between jobs must not make their `needs` form a cycle.

The compiler adds a `needs` edge from every consumer job to the job that
produces an output it reads.  Combined with explicit `needs:` (or with the
reverse flow) that can close a loop, which GitHub rejects.  A cycle made of
explicit `needs:` alone is DAG001’s.

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
