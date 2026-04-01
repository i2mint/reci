---
name: reci-dev
description: >
  Guide for contributing to the reci codebase. Use this skill when the user wants to
  add features, fix bugs, add validation rules, add config adapters, or understand
  reci's architecture. Trigger when the user says things like "I want to add a rule",
  "how does the compiler work", "I want to contribute to reci", or asks about
  reci internals.
---

# Contributing to reci

## Architecture overview

reci compiles a **recipe** (simplified workflow YAML) into a GitHub Actions **workflow** through this pipeline:

```
recipe.yml  ──parse──>  Recipe  ──graph──>  RecipeGraph  ──compile──>  workflow dict  ──dump──>  ci.yml
                          │                     │                           ▲
                     action_spec.py         validation/                compiler.py
                     (fetch action.yml,     (DAG, FLOW,               (five-level resolution,
                      typed contracts)       CONF rules)               config injection,
                                                                       cross-job wiring)
```

**Key data flow:**
1. `recipe.py` parses YAML into `Recipe` / `JobSpec` / `StepSpec` dataclasses
2. `action_spec.py` fetches `action.yml` from GitHub, producing `ActionSpec` with typed `InputSpec` / `OutputSpec`
3. `graph.py` builds a `RecipeGraph` — a two-level DAG (jobs contain sequential steps, jobs run in parallel)
4. `compiler.py` resolves inputs via five-level precedence, injects setup job, generates cross-job wiring
5. `yaml_gen.py` serializes to YAML via ruamel.yaml

## Adding a validation rule

1. Choose a rule prefix: `DAG` (structure), `FLOW` (data flow), `CONF` (config), `PURE` (purity), `ACT` (actions)
2. Pick the next number in that prefix's sequence
3. Create or add to the appropriate file in `reci/validation/rules/`:
   - `dag.py` for structural rules
   - `flow.py` for data-flow rules
   - `config_rules.py` for config rules
   - `purity.py` for run-step rules
   - `action.py` for action-related rules
4. Write a function that takes `(graph: RecipeGraph, config: dict)` and returns a list of `Finding` objects
5. Register it in `reci/validation/rules/__init__.py` by adding to the `RULES` list

A `Finding` has: `rule` (e.g. "FLOW007"), `severity` (error/warning/info), `message`, `location` (optional), `suggestion` (optional).

## Adding a config adapter

1. Create `reci/adapters/my_adapter.py`
2. Implement the `ConfigAdapter` protocol from `reci/adapters/base.py`:
   - `name` property
   - `default_path()` — where to look by default
   - `read(path) -> dict` — parse the config file and return flat dict
   - `write(path, config)` — write config back (for scaffold)
3. Register in `reci/adapters/__init__.py`

## Testing

```bash
pytest                          # run all tests
pytest --doctest-modules        # include doctests
pytest -v --tb=short            # verbose with short tracebacks
```

## Code style

- `ruff format .` then `ruff check .`
- Docstrings on public functions (Google convention)
- Type hints on function signatures
- Prefer dataclasses for structured data, plain dicts for unstructured workflow output
