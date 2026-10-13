# reci.validation.rules.config_rules

Config validation rules (CONF001–CONF003).

### Functions

| [`check_exportable_config`](#reci.validation.rules.config_rules.check_exportable_config)(graph, config)           | Config keys must be valid output ids; values must survive $GITHUB_OUTPUT.   |
|---------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`check_missing_required_config`](#reci.validation.rules.config_rules.check_missing_required_config)(graph, config)     | Config keys that are required but not present.                              |
| [`check_undefined_config_references`](#reci.validation.rules.config_rules.check_undefined_config_references)(graph, config) | `${{ config.X }}` where `X` is not a config key.                            |
| [`check_unused_config`](#reci.validation.rules.config_rules.check_unused_config)(graph, config)               | Config keys present but not referenced by any action.                       |

### reci.validation.rules.config_rules.check_exportable_config(graph, config)

Config keys must be valid output ids; values must survive $GITHUB_OUTPUT.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]

### reci.validation.rules.config_rules.check_missing_required_config(graph, config)

Config keys that are required but not present.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]

### reci.validation.rules.config_rules.check_undefined_config_references(graph, config)

`${{ config.X }}` where `X` is not a config key.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]

### reci.validation.rules.config_rules.check_unused_config(graph, config)

Config keys present but not referenced by any action.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]
