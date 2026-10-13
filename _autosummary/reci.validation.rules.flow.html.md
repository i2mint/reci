# reci.validation.rules.flow

Data-flow validation rules (FLOW001–FLOW006).

### Functions

| [`check_ambiguous_wiring`](#reci.validation.rules.flow.check_ambiguous_wiring)(graph, config)          | An input name matches multiple upstream outputs.                 |
|-------------------------------------------------------------------------------------------------|------------------------------------------------------------------|
| [`check_boolean_coercion`](#reci.validation.rules.flow.check_boolean_coercion)(graph, config)          | A string output is wired to a likely-boolean input.              |
| [`check_matrix_output`](#reci.validation.rules.flow.check_matrix_output)(graph, config)             | Matrix job outputs consumed by downstream are non-deterministic. |
| [`check_unsourced_required_inputs`](#reci.validation.rules.flow.check_unsourced_required_inputs)(graph, config) | Required input has no source at any level.                       |
| [`check_unused_outputs`](#reci.validation.rules.flow.check_unused_outputs)(graph, config)            | An output is declared but never consumed downstream.             |

### reci.validation.rules.flow.check_ambiguous_wiring(graph, config)

An input name matches multiple upstream outputs.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]

### reci.validation.rules.flow.check_boolean_coercion(graph, config)

A string output is wired to a likely-boolean input.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]

### reci.validation.rules.flow.check_matrix_output(graph, config)

Matrix job outputs consumed by downstream are non-deterministic.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]

### reci.validation.rules.flow.check_unsourced_required_inputs(graph, config)

Required input has no source at any level.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]

### reci.validation.rules.flow.check_unused_outputs(graph, config)

An output is declared but never consumed downstream.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]
