# reci.validation.rules.config_rules

Config validation rules (CONF001–CONF007).

### Functions

| [`check_empty_value_shadows_default`](#reci.validation.rules.config_rules.check_empty_value_shadows_default)(graph, config)   | An empty-string config value on an input that has an action default (it replaces it).   |
|-----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| [`check_exportable_config`](#reci.validation.rules.config_rules.check_exportable_config)(graph, config)             | Config keys must be valid output ids; values must survive $GITHUB_OUTPUT.               |
| [`check_leftover_placeholders`](#reci.validation.rules.config_rules.check_leftover_placeholders)(graph, config)         | `<REQUIRED: ...>` values that `reci scaffold` wrote and nobody filled in.               |
| [`check_missing_required_config`](#reci.validation.rules.config_rules.check_missing_required_config)(graph, config)       | Config keys that are required but not present.                                          |
| [`check_undefined_config_references`](#reci.validation.rules.config_rules.check_undefined_config_references)(graph, config)   | `${{ config.X }}` where `X` is not a config key.                                        |
| [`check_unused_config`](#reci.validation.rules.config_rules.check_unused_config)(graph, config)                 | Config keys present but not referenced by any action.                                   |

### reci.validation.rules.config_rules.check_empty_value_shadows_default(graph, config)

An empty-string config value on an input that has an action default (it replaces it).

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]

### reci.validation.rules.config_rules.check_exportable_config(graph, config)

Config keys must be valid output ids; values must survive $GITHUB_OUTPUT.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](reci.validation.report.html.md#reci.validation.report.Finding)]

### reci.validation.rules.config_rules.check_leftover_placeholders(graph, config)

`<REQUIRED: ...>` values that `reci scaffold` wrote and nobody filled in.

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
