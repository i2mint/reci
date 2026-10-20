# reci.validation.rules

Validation rule registry and runner.

### Functions

| [`register_rule`](#reci.validation.rules.register_rule)(rule_id)                  | Decorator to register a validation rule function.    |
|------------------------------------------------------------------------------------------|------------------------------------------------------|
| [`run_all_rules`](#reci.validation.rules.run_all_rules)(graph, config, \*[, ...]) | Run all registered rules and return a merged report. |

### reci.validation.rules.register_rule(rule_id)

Decorator to register a validation rule function.

### reci.validation.rules.run_all_rules(graph, config, , severity_overrides=None, disabled_rules=None)

Run all registered rules and return a merged report.

* **Return type:**
  [`ValidationReport`](reci.validation.report.html.md#reci.validation.report.ValidationReport)

### Modules

| [`action`](reci.validation.rules.action.html.md#module-reci.validation.rules.action)             | Action metadata validation rules (ACT001–ACT003).   |
|---------------------------------------------------------------------------------------------------------|-----------------------------------------------------|
| [`config_rules`](reci.validation.rules.config_rules.html.md#module-reci.validation.rules.config_rules) | Config validation rules (CONF001–CONF007).          |
| [`dag`](reci.validation.rules.dag.html.md#module-reci.validation.rules.dag)                   | DAG structure validation rules (DAG001–DAG004).     |
| [`flow`](reci.validation.rules.flow.html.md#module-reci.validation.rules.flow)                 | Data-flow validation rules (FLOW001–FLOW007).       |
| [`purity`](reci.validation.rules.purity.html.md#module-reci.validation.rules.purity)             | Purity validation rules (PURE001–PURE003).          |
