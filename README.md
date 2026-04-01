
# reci

Compile declarative CI recipes into fully-wired GitHub Actions workflows with typed data-flow validation.

To install:	```pip install reci```

## Why reci

Writing GitHub Actions workflows by hand means wading through hundreds of lines of
boilerplate: forwarding step outputs to job outputs, threading `needs.X.outputs.Y`
expressions across jobs, and copy-pasting config values that belong in one place.
When something changes you touch a dozen lines across three jobs — and one typo
silently breaks your pipeline.

**reci** lets you write a short recipe that says *what* your CI does (which actions,
in what order, with what config), and the compiler handles *how* — auto-wiring
cross-job outputs, injecting config from `pyproject.toml`, and validating data-flow
before you push.

## Agent skills (recommended)

reci ships with CLI and Python APIs (see [below](#cli)), but the best way to use it
is through **AI agent skills** — structured instructions that let coding assistants
operate reci on your behalf. Instead of memorizing CLI flags and YAML syntax, just
say what you want:

- *"Set up CI for this project"*
- *"Migrate my existing workflow to reci"*
- *"What CI actions make sense here?"*

### Available skills

| Skill | What it does |
|-------|-------------|
| [ci-setup](.claude/skills/ci-setup/) | Examines your project, proposes a CI plan, writes a recipe, compiles to a workflow |
| [ci-migrate](.claude/skills/ci-migrate/) | Converts an existing GitHub Actions workflow into a reci recipe |
| [ci-advisor](.claude/skills/ci-advisor/) | Interactive discussion about what CI pipeline makes sense for your project |
| [reci-dev](.claude/skills/reci-dev/) | Guide for contributors — architecture, adding rules, adding adapters |

### Using the skills

**Claude Code** — symlink or copy the skills into your project or your personal skills directory:

```bash
# Make available to all your projects
ln -s /path/to/reci/.claude/skills/ci-setup ~/.claude/skills/ci-setup
ln -s /path/to/reci/.claude/skills/ci-migrate ~/.claude/skills/ci-migrate
ln -s /path/to/reci/.claude/skills/ci-advisor ~/.claude/skills/ci-advisor

# Or just for one project
ln -s /path/to/reci/.claude/skills/ci-setup my-project/.claude/skills/ci-setup
```

Then invoke with `/ci-setup`, `/ci-migrate`, or `/ci-advisor` in Claude Code.
See the [Claude Code skills docs](https://docs.anthropic.com/en/docs/claude-code/skills) for details.

**Other agents** — the skills are plain Markdown files following the open
[Agent Skills standard](https://agentskills.org). For Cursor, Copilot, Windsurf,
and other tools, see the standard's
[integration guide](https://agentskills.org/integrations).

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
