# Claude Code Prompt: Build `reci` — the CI Recipe Tool

## Context

You have two reference documents in this project:

1. **`misc/docs/wads_ci_architecture_analysis.md`** — Describes how the existing Python CI system (wads/isee) works today. This is the pattern we're generalizing. Read this first to understand the three-layer architecture (static workflow template + composite actions + per-project config) and its design tensions (SSOT vs mixed concerns, `@master` fragility, bootstrap dependency, custom logic limitations, indirection depth). The new tool should address all five tensions.

2. **`misc/docs/ci_tool_research_report.md`** — The full research and design spec for the new tool. This covers: action.yml parsing strategy, library choices (ruamel.yaml for YAML, tomlkit for TOML), the pluggable config adapter pattern, the flat-with-`__`-overrides config namespace, existing tool landscape (nothing does this), CI concern audit across Python and frontend, and two example recipes (frontend-library and python-library) that serve as acceptance tests. **This is the primary design document. Follow its recommendations.**

## What to Build

A Python package called **`reci`** that implements a **CI recipe compiler and config validator** for GitHub Actions.

### The Core Loop

```
recipe.yml + action.yml introspection → CI YAML + config schema
config file + config schema → validation report
```

### The Five Abstractions

1. **Recipe** — A YAML file listing GitHub Action references grouped into jobs, with optional inline `run:` steps. Supports `${{ config.* }}` references to config values. See the addendum in the research report for concrete examples.

2. **ActionSpec** — Parsed from an action's `action.yml`. Contains the input contract: name → {required, default, description}. Fetched from GitHub (raw URL, with API fallback) or declared manually in the recipe.

3. **Config** — A flat `dict[str, Any]` with `action__key` scoped overrides. Resolution order for input `root_dir` of action `run-tests`: (a) `run_tests__root_dir` in config, (b) `root_dir` in config, (c) `default` from action.yml, (d) validation error if required.

4. **ConfigAdapter** — Protocol for reading/writing config to/from files. Built-in adapters: `PyprojectTomlAdapter` (reads `[tool.ci]`), `WadsAdapter` (reads `[tool.wads.ci]` for backward compat), `PackageJsonAdapter` (reads `"ci"` key), `YamlAdapter` (reads `.ci.yml`). The adapter is a pluggable strategy — the core never knows the file format.

5. **Compiler** — Takes a recipe + resolved action specs → produces a complete GitHub Actions workflow YAML. The compiler: (a) injects a `setup` job that reads config and exports values as job outputs, (b) adds `needs: [setup]` to all other jobs, (c) auto-wires each action's `with:` block from config, (d) replaces `${{ config.* }}` with `${{ needs.setup.outputs.* }}`.

### CLI Interface

Use `argh` for CLI dispatch. Core commands:

```
reci compile <recipe> [--config-adapter pyproject] [--output .github/workflows/ci.yml]
    # Compile recipe → CI YAML. Also prints config schema.

reci validate [--config-adapter pyproject] [--recipe recipe.yml]
    # Validate that config file satisfies the schema derived from the recipe.
    # Hard errors for missing required keys, soft warnings for missing optional keys.

reci scaffold <recipe> [--config-adapter pyproject]
    # Generate both CI YAML and config file skeleton. Patch config if it exists, create if not.

reci inspect <action-ref>
    # Fetch and display an action's input contract. E.g.: reci inspect i2mint/wads/actions/run-tests@master
```

### Key Design Principles (from the research)

- **ruamel.yaml** for all YAML operations — it handles the `on:` key correctly (PyYAML treats it as boolean `True`) and preserves comments/style for round-tripping.
- **tomlkit** for TOML round-trip editing — the only Python library that preserves comments and formatting.
- **Programmatic YAML construction**, not Jinja2 templates — build a Python dict, dump with ruamel.yaml. More testable, avoids indentation bugs.
- **Flat config with `__` overrides** — `root_dir` is shared, `run_tests__root_dir` overrides for a specific action. Resolution is a simple two-level lookup.
- **Don't patch TypeScript files** — generate fresh or tell the user what to add. Validation is the priority, not perfect round-trip editing of every format.
- **Progressive disclosure** — zero-config should work (auto-detection from package.json or pyproject.toml), power users get full control via recipe + config.
- **Validation-first** — the tool's most important job is catching mismatches between what the CI YAML expects and what the config provides, not generating perfect files.

### Package Structure

Follow the python-package-architecture and python-coding-standards skills. The package should use:
- `pyproject.toml` with hatchling or setuptools
- `argh` for CLI dispatch from `__main__.py`
- Mapping/Protocol patterns for the config adapter
- Doctests for core functions
- Progressive disclosure in the API (simple things simple)

### What NOT to Build (yet)

- npm package wrapper
- TypeScript config file patching (magicast etc.)
- Composite action scaffolding
- Template lifecycle management (Copier-style updates)
- GitHub API authentication flow (start with public repos only)

### Acceptance Tests

The tool should be able to:
1. Parse the `recipes/frontend-library.yml` example from the research report addendum and produce valid CI YAML
2. Parse the `recipes/python-library.yml` example and produce valid CI YAML
3. Detect that `node_version` is required from the frontend recipe and flag it as missing if not in config
4. Auto-discover inputs from `actions/setup-node@v6` by fetching its action.yml from GitHub
5. Round-trip edit a pyproject.toml file (add `[tool.ci]` section) without destroying existing content
