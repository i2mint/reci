
# reci

Compile declarative CI recipes into fully-wired GitHub Actions workflows with typed data-flow validation.

To install:	```pip install reci```

## What it does

Write a short recipe YAML describing your CI pipeline as a DAG of GitHub Actions.
`reci` introspects each action's `action.yml` for typed input/output contracts,
infers data-flow edges from variable names, injects config from `pyproject.toml`,
and compiles the whole thing into a complete workflow YAML — with all the
cross-job output wiring generated for you.

## Quick start

```python
from reci import parse_recipe_string, compile_recipe, dump_workflow, ActionSpec, InputSpec, OutputSpec

recipe = parse_recipe_string("""
name: CI
on: [push, pull_request]

jobs:
  test:
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '${{ config.python_version }}'
      - id: run_tests
        run: pytest
""")

# Action specs can be fetched from GitHub or provided manually
specs = {
    "actions/checkout@v4": ActionSpec(ref="actions/checkout@v4"),
    "actions/setup-python@v5": ActionSpec(
        ref="actions/setup-python@v5",
        inputs={"python_version": InputSpec(name="python_version", default="3.x")},
    ),
}

config = {"python_version": "3.12"}
workflow = compile_recipe(recipe, specs, config=config)
print(dump_workflow(workflow))
```

The compiler:
- Injects a `setup` job that exports config values as job outputs
- Rewrites `${{ config.* }}` to `${{ needs.setup.outputs.* }}`
- Auto-wires `needs:` edges from data-flow dependencies
- Generates the cross-job output forwarding ceremony (step output -> job output -> `needs` consumption)

## CLI

```bash
# Inspect an action's input/output contract
reci inspect actions/setup-python@v5

# Compile a recipe to workflow YAML
reci compile recipe.yml --output .github/workflows/ci.yml

# Validate a recipe + config
reci validate --recipe recipe.yml --format cli

# Scaffold a config skeleton from a recipe
reci scaffold recipe.yml
```

## Five-level input resolution

For each action input, the compiler resolves its value using this precedence:

1. **Explicit `with:`** in the recipe — used verbatim
2. **Upstream output match** — `${{ steps.<id>.outputs.<name> }}`
3. **Config value** (scoped `action__key`, then shared `key`) — `${{ needs.setup.outputs.<key> }}`
4. **Default from action.yml** — omitted (GitHub uses the default)
5. **Required + no source** — validation error

## Validation

ESLint-style severity (`error`/`warning`/`info`) with ruff-style rule prefixes:

| Rule | Category | What it catches |
|------|----------|----------------|
| DAG001 | Structure | Cycle detected |
| DAG002 | Structure | Duplicate output name in a job |
| FLOW001 | Data flow | Required input has no source |
| FLOW002 | Data flow | Ambiguous wiring (multiple upstream matches) |
| FLOW006 | Data flow | Matrix job output consumed downstream (non-deterministic) |
| CONF001 | Config | Required config key missing |
| PURE001 | Purity | `run:` step breaks typed contract |
| ACT002 | Action | Referenced action not found |

## Config adapters

Read CI config from your project file of choice:

| Adapter | Section | Library |
|---------|---------|---------|
| `pyproject` | `[tool.ci]` | tomlkit (round-trip) |
| `wads` | `[tool.wads.ci]` | tomlkit |
| `package-json` | `"ci"` key | json |
| `yaml` | `.ci.yml` | ruamel.yaml |

## The recipe format

A recipe looks like a GitHub Actions workflow with reci extensions:

- **`${{ config.* }}`** — references to config values (resolved from pyproject.toml etc.)
- **`bind:`** — input renaming (`bind: {tag_name: version}` wires upstream output `version` to input `tag_name`)
- **`outputs:`** on `run:` steps — manual output annotation for untyped steps

```yaml
name: Python CI
on: [push, pull_request]

jobs:
  test:
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '${{ config.python_version }}'
      - run: pytest

  publish:
    needs: [test]
    steps:
      - uses: actions/checkout@v4
      - id: bump
        uses: i2mint/isee/actions/bump-version-number@master
      - uses: i2mint/wads/actions/git-tag@master
        bind:
          tag_name: version  # wire bump's "version" output to git-tag's "tag_name" input
```
