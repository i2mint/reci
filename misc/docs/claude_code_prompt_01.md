# Claude Code Prompt: Build `reci` — Typed DAG Compilation for GitHub Actions


> **Note (updated):** this document originally prescribed `argh` for CLI dispatch.
> `reci` now uses [`cw`](https://github.com/i2mint/cw), which reproduces argh's
> grammar on plain `argparse` under MIT with no runtime dependencies. The mentions
> below have been updated so this document does not re-seed the old choice.

## Context Documents

You have the following reference documents in `misc/docs/`:

- **`ci_tool_research_report.md`** — **The primary design document.** Comprehensive report covering the CI-as-DAG survey, gap analysis, and reci's full architecture. Follow its recommendations for all design decisions. Read this first.
- **`wads_ci_architecture_analysis.md`** — How the existing Python CI system (wads/isee) works. The three-layer pattern reci generalizes. Read this to understand what we're improving on.
- **`claude_code_prompt.md`** — This file. Implementation instructions.
- **`research/reci 01*.md`** — Deep dive: how Dagger, Tekton, Argo, Concourse, GitHub Actions model DAGs. Reference when implementing RecipeGraph and data-flow wiring.
- **`research/reci 02*.md`** — Deep dive: GitHub Actions output wiring edge cases. Reference when implementing the Compiler's output forwarding logic. Critical for cross-job wiring and matrix output handling.
- **`research/reci 03*.md`** — Deep dive: validation tools and patterns. Reference when implementing the validation rule system (ESLint severity model, fixability taxonomy, output formats).
- **`research/reci 04*.md`** — Deep dive: meshed vs graphlib evaluation. Reference for the DAG engine decision (graphlib.TopologicalSorter is the choice).

## What to Build

A Python package called **`reci`** — a CI recipe compiler and data-flow validator for GitHub Actions.

### The Core Idea

A "recipe" is a declarative YAML file describing a CI pipeline as a computational DAG. Nodes are GitHub Action references (or inline `run:` steps). Edges are data dependencies inferred from variable names (action A outputs `version`, action B inputs `version` → edge). External parameters come from a project config file (pyproject.toml, package.json, etc.) via pluggable adapters.

The tool compiles `recipe + action.yml introspection + config → workflow YAML` and validates the entire data-flow graph at compile time.

### The Five Abstractions

**1. ActionSpec** (`action_spec.py`)
Parsed from an action's `action.yml`. Contains input/output contracts (name, required, default, description). Fetch from GitHub via raw URL (with API fallback) or manual declaration in recipe.

**2. RecipeGraph** (`graph.py`)
The computational DAG. Built on `graphlib.TopologicalSorter` (stdlib). Nodes are `ActionNode` frozen dataclasses carrying ActionSpec + step ID + job grouping + output names + optional input renaming (`bind`). Edges represent data flow. External inputs come from config. Provides:
- `execution_waves()` — parallel groups via `get_ready()`/`done()`
- `validate()` → `ValidationReport`
- Cycle detection (built-in `CycleError`)
- Two-level structure: jobs containing steps

**3. Config** (`config.py`)
A flat `dict[str, Any]` with `action__key` scoped overrides. Resolution order for input `root_dir` of action `run-tests`:
1. `run_tests__root_dir` in config → use it (scoped override wins)
2. `root_dir` in config → use it (shared default)
3. `default` from action.yml → use it (action default)
4. If required and none found → validation error (FLOW001)

The `__` separator uses the action's local name (last path segment, normalized to underscores).

**4. ConfigAdapter** (`adapters/base.py`)
Protocol for reading/writing config to/from files. Built-in adapters:
- `PyprojectTomlAdapter` — reads `[tool.ci]` via tomlkit, round-trip preserving comments
- `WadsAdapter` — reads `[tool.wads.ci]` for backward compat
- `PackageJsonAdapter` — reads `"ci"` key via json
- `YamlAdapter` — reads `.ci.yml` via ruamel.yaml

**5. Compiler** (`compiler.py`)
Takes recipe + resolved action specs + config → produces GitHub Actions workflow YAML. The compiler:
- Injects a `setup` job that reads config and exports values as job outputs
- Adds `needs:` edges inferred from data-flow dependencies
- Auto-wires each action's `with:` block from config and upstream outputs
- Auto-generates the cross-job output forwarding ceremony (step output → job output → needs consumption)
- Replaces `${{ config.* }}` with `${{ needs.setup.outputs.* }}`
- Handles input renaming via `bind` mappings

### Data Flow Wiring

The compiler resolves each action input via five-level precedence:
1. Explicit `with:` in recipe → verbatim
2. Upstream output name match → `${{ steps.<id>.outputs.<n> }}`
3. Config value (scoped `__` then shared) → `${{ needs.setup.outputs.<key> }}`
4. Default from action.yml → omit
5. None + required → validation ERROR

Name matching: normalize to lowercase, treat hyphens as underscores.

### Validation System

Use the plain dataclass + custom validator pattern (no framework). ESLint-style severity (`off`/`warn`/`error`), ruff-style prefix grouping.

```python
class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Finding:
    rule_id: str
    severity: Severity
    message: str
    location: str | None = None
    suggestion: str | None = None
    fixable: bool = False
```

Rule categories: `DAG*` (structure), `FLOW*` (data flow), `CONF*` (config), `PURE*` (purity), `ACT*` (action metadata). See the research report §4.6 for the full rule catalog.

Key rules:
- `DAG001`: Cycle detected
- `DAG002`: Duplicate output name
- `FLOW001`: Required input has no source
- `FLOW002`: Ambiguous wiring (multiple upstream outputs match)
- `FLOW006`: Matrix job output consumed downstream (non-deterministic)
- `CONF001`: Required config key missing
- `PURE001`: `run:` step breaks typed contract
- `ACT002`: Referenced action not found

### Handling `run:` Steps (Purity)

`run:` steps are allowed but flagged. Three-tier approach:
1. Detect `${{ }}` references (implicit inputs) and `>> $GITHUB_OUTPUT` patterns (implicit outputs)
2. Suggest refactoring into composite actions
3. Allow manual annotation in recipe: `outputs: [version]` on a `run:` step

### CLI Interface

Use `cw` for CLI dispatch:

```
reci compile <recipe> [--config-adapter pyproject] [--output .github/workflows/ci.yml]
reci validate [--config-adapter pyproject] [--recipe recipe.yml]
reci scaffold <recipe> [--config-adapter pyproject]
reci inspect <action-ref>
```

### Key Libraries

| Package | Purpose | Why |
|---------|---------|-----|
| `ruamel.yaml` | Parse action.yml, generate CI YAML | YAML 1.2 (handles `on:` key), preserves style |
| `tomlkit` | Round-trip edit pyproject.toml | Only TOML library preserving comments |
| `cw` | CLI dispatch | Author's preferred pattern (argparse-native, MIT, zero runtime deps) |
| `httpx` | Fetch action.yml from GitHub | HTTP client |

### YAML Generation

Use `ruamel.yaml` programmatically — build a Python dict, dump it. **No Jinja2 templates.** PyYAML treats `on` as boolean `True` — do not use it. Use `SingleQuotedScalarString` for `${{ }}` expressions to preserve quoting.

### Package Structure

```
reci/
├── __init__.py
├── __main__.py
├── action_spec.py
├── recipe.py
├── graph.py
├── compiler.py
├── config.py
├── adapters/
│   ├── __init__.py
│   ├── base.py
│   ├── pyproject.py
│   ├── wads.py
│   ├── package_json.py
│   └── yaml_adapter.py
├── validation/
│   ├── __init__.py
│   ├── report.py
│   ├── rules/
│   │   ├── dag.py
│   │   ├── flow.py
│   │   ├── config.py
│   │   ├── purity.py
│   │   └── action.py
│   └── formatters.py
└── yaml_gen.py
```

Follow the python-package-architecture and python-coding-standards skills for conventions (pyproject.toml with hatchling/setuptools, `cw` CLI dispatch, Mapping/Protocol patterns, doctests).

### Development Phases

**Phase 1** — Core loop: ActionSpec parsing, RecipeGraph, Compiler producing valid YAML from a simple recipe.
**Phase 2** — DAG data flow: output-to-input wiring by name matching within a job.
**Phase 3** — Validation: full rule set.
**Phase 4** — Config adapters: PyprojectTomlAdapter, PackageJsonAdapter.
**Phase 5** — Cross-job wiring: three-step forwarding ceremony, two-level DAG.
**Phase 6** — CLI + output formats.

### What NOT to Build (yet)

- npm package wrapper
- TypeScript config file patching
- Composite action scaffolding
- Template lifecycle management
- GitHub API authentication (start with public repos only)

### Acceptance Tests

1. Parse a Python library recipe and produce valid GitHub Actions YAML
2. Auto-wire a version bumping action's output to a git-tag action's input
3. Detect that `python_versions` is required and flag it missing from config
4. Auto-discover inputs from `actions/setup-node@v6` by fetching action.yml
5. Round-trip edit pyproject.toml (add `[tool.ci]` section) without destroying content
6. Detect a cycle in a recipe and report it with human-readable error
7. Flag a `run:` step as `PURE001` and suggest factoring into an action
