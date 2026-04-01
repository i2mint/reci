# reci

Declarative CI recipe compiler for GitHub Actions.

## What reci does

`reci` takes a simplified "recipe" YAML and compiles it into a fully-wired GitHub Actions workflow. It introspects each action's `action.yml` for typed input/output contracts, infers data-flow edges from variable names, injects config from `pyproject.toml` (or other sources), and generates all the cross-job output wiring automatically.

## Project layout

```
reci/
  __init__.py          # Public API exports
  __main__.py          # CLI: compile, validate, scaffold, inspect
  recipe.py            # Recipe model (Recipe, JobSpec, StepSpec)
  action_spec.py       # Action contracts (ActionSpec, InputSpec, OutputSpec)
  compiler.py          # Recipe + specs + config -> workflow YAML
  graph.py             # Two-level DAG (RecipeGraph, ActionNode, CrossJobEdge)
  config.py            # Config resolution with scoped overrides
  yaml_gen.py          # YAML I/O (ruamel.yaml wrapper)
  adapters/            # Pluggable config readers (pyproject, wads, package-json, yaml)
  validation/          # ESLint-style validation rules (DAG, FLOW, CONF, PURITY, ACT)
    rules/             # Individual rule implementations
```

## Key concepts

- **Recipe**: Simplified workflow YAML with `${{ config.* }}`, `bind:`, and `outputs:` extensions
- **Five-level input resolution**: explicit `with:` > upstream output match > config > action default > error
- **Config adapters**: Read CI config from `[tool.ci]` in pyproject.toml, `[tool.wads.ci]`, package.json, or `.ci.yml`
- **Validation rules**: DAG001-DAG004, FLOW001-FLOW006, CONF001/CONF003, PURE001-PURE002, ACT002

## CLI

```bash
reci compile recipe.yml --output .github/workflows/ci.yml
reci validate --recipe recipe.yml --format cli
reci scaffold recipe.yml
reci inspect actions/setup-python@v5
```

## Development

- Python 3.10+, dependencies: ruamel.yaml, httpx, tomlkit, argh
- Format: `ruff format .` | Lint: `ruff check .` | Test: `pytest`
- Adding a validation rule: create a function in `reci/validation/rules/`, register it in `__init__.py`
- Adding a config adapter: implement `ConfigAdapter` protocol in `reci/adapters/`, register in `__init__.py`
