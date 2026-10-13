# reci.validation.rules.config_rules

Config validation rules (CONF001–CONF003).

### Functions

| [`check_missing_required_config`](#reci.validation.rules.config_rules.check_missing_required_config)(graph, config)   | Config keys that are required but not present.        |
|-------------------------------------------------------------------------------------------------|-------------------------------------------------------|
| [`check_unused_config`](#reci.validation.rules.config_rules.check_unused_config)(graph, config)             | Config keys present but not referenced by any action. |

### reci.validation.rules.config_rules.check_missing_required_config(graph, config)

Config keys that are required but not present.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]

### reci.validation.rules.config_rules.check_unused_config(graph, config)

Config keys present but not referenced by any action.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]
