# reci.validation.rules.flow

Data-flow validation rules (FLOW001–FLOW006).

### Functions

| [`check_ambiguous_wiring`](#reci.validation.rules.flow.check_ambiguous_wiring)(graph, config)          | An input name matches multiple upstream outputs, in a job or across jobs.    |
|-------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`check_boolean_coercion`](#reci.validation.rules.flow.check_boolean_coercion)(graph, config)          | A string output is wired to a likely-boolean input.                          |
| [`check_matrix_output`](#reci.validation.rules.flow.check_matrix_output)(graph, config)             | A job output consumed by another job comes from a matrix or conditional job. |
| [`check_unsourced_required_inputs`](#reci.validation.rules.flow.check_unsourced_required_inputs)(graph, config) | Required input has no source at any level.                                   |
| [`check_unused_outputs`](#reci.validation.rules.flow.check_unused_outputs)(graph, config)            | An output is declared but never consumed downstream.                         |

### reci.validation.rules.flow.check_ambiguous_wiring(graph, config)

An input name matches multiple upstream outputs, in a job or across jobs.

Within a job the nearest preceding step wins.  Across jobs there is no
nearer: the first producing job in recipe order is used.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]

### reci.validation.rules.flow.check_boolean_coercion(graph, config)

A string output is wired to a likely-boolean input.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]

### reci.validation.rules.flow.check_matrix_output(graph, config)

A job output consumed by another job comes from a matrix or conditional job.

A matrix job has one output value for all its legs: whichever leg finishes
last wins.  A job with an `if:` that is false is skipped, and so is every
job that `needs` it (unless it uses `always()` or similar).

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]

### reci.validation.rules.flow.check_unsourced_required_inputs(graph, config)

Required input has no source at any level.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]

### reci.validation.rules.flow.check_unused_outputs(graph, config)

An output is declared but never consumed downstream.

Consumed means: matched by an input of a later step (by name, honouring
`bind:`), or referenced explicitly as `steps.<id>.outputs.<name>` (dot or
bracket syntax, ids compared case-insensitively) in a step of the same job:
its `with:`, `env:`, `run:`, `if:`, `name:` or other keys, or in a
job `outputs:` entry (a job’s other fields cannot read `steps`).
`needs.` references are not counted: only the compiler’s own forwarding and
the job `outputs:` the recipe declares make them resolve.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]
