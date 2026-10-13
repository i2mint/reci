# reci

reci — Compile declarative CI recipes into GitHub Actions workflows.

### Modules

| [`action_spec`](reci.action_spec.html.md#module-reci.action_spec)   | Action contract model — parsed from `action.yml` metadata.                                                               |
|----------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------|
| [`adapters`](reci.adapters.html.md#module-reci.adapters)         | Config adapter registry.                                                                                                 |
| [`compiler`](reci.compiler.html.md#module-reci.compiler)         | Compiler — recipe + action specs + config → GitHub Actions workflow YAML.                                                |
| [`config`](reci.config.html.md#module-reci.config)             | Config resolution — flat dict with scoped overrides.                                                                     |
| [`graph`](reci.graph.html.md#module-reci.graph)               | Recipe DAG — computational graph built on [`graphlib`](https://docs.python.org/3/library/graphlib.html#module-graphlib). |
| [`recipe`](reci.recipe.html.md#module-reci.recipe)             | Recipe model — declarative CI pipeline description.                                                                      |
| [`validation`](reci.validation.html.md#module-reci.validation)     | Validation system — ESLint-style severity, ruff-style rule prefixes.                                                     |
| [`yaml_gen`](reci.yaml_gen.html.md#module-reci.yaml_gen)         | YAML I/O wrapper using ruamel.yaml (YAML 1.2).                                                                           |
