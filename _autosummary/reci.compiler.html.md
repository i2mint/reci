# reci.compiler

Compiler — recipe + action specs + config → GitHub Actions workflow YAML.

The compiler resolves data-flow wiring using a five-level precedence, injects
a `setup` job that exports config values as job outputs, auto-generates the
cross-job output forwarding ceremony, and adds `needs:` edges from data-flow
dependencies.

### Functions

| [`compile_recipe`](#reci.compiler.compile_recipe)(recipe, action_specs, \*[, config])   | Compile a recipe into a GitHub Actions workflow dict.                        |
|-------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`describe_cycle_edges`](#reci.compiler.describe_cycle_edges)(cycle, edges)                   | The data-flow reads that justify each `consumer -> producer` hop of *cycle*. |
| [`detect_cross_job_edges`](#reci.compiler.detect_cross_job_edges)(graph, config)                | Find data-flow edges between steps in different jobs.                        |

### Exceptions

| [`CompilationError`](#reci.compiler.CompilationError)   | Raised when compilation fails.   |
|---------------------------------------------------------------------|----------------------------------|

### *exception* reci.compiler.CompilationError

Bases: [`Exception`](https://docs.python.org/3/builtins/exceptions.html#Exception)

Raised when compilation fails.

### reci.compiler.compile_recipe(recipe, action_specs, , config=None)

Compile a recipe into a GitHub Actions workflow dict.

* **Parameters:**
  * **recipe** ([`Recipe`](reci.recipe.html.md#reci.recipe.Recipe)) – Parsed recipe.
  * **action_specs** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`ActionSpec`](reci.action_spec.html.md#reci.action_spec.ActionSpec)]) – Action specs keyed by ref string.
  * **config** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Flat config dict (optional).  If non-empty, a `setup` job is
    injected, jobs depend on it, and config references are wired.
    Cross-job data-flow wiring happens either way.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### reci.compiler.describe_cycle_edges(cycle, edges)

The data-flow reads that justify each `consumer -> producer` hop of *cycle*.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### reci.compiler.detect_cross_job_edges(graph, config)

Find data-flow edges between steps in different jobs.

Public: the validation rules use the same detection as the compiler.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`CrossJobEdge`](reci.graph.html.md#reci.graph.CrossJobEdge)]
