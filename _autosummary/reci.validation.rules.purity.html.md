# reci.validation.rules.purity

Purity validation rules (PURE001–PURE003).

### Functions

| [`check_run_step_outputs`](#reci.validation.rules.purity.check_run_step_outputs)(graph, config)   | A run: step writes to $GITHUB_OUTPUT.              |
|------------------------------------------------------------------------------------------|----------------------------------------------------|
| [`check_run_steps`](#reci.validation.rules.purity.check_run_steps)(graph, config)          | Any run: step breaks the typed data-flow contract. |

### reci.validation.rules.purity.check_run_step_outputs(graph, config)

A run: step writes to $GITHUB_OUTPUT.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]

### reci.validation.rules.purity.check_run_steps(graph, config)

Any run: step breaks the typed data-flow contract.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]
