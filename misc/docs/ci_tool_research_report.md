# `reci`: Typed DAG Compilation for GitHub Actions

_A survey of CI pipeline modeling, a gap analysis, and the design of a recipe-based CI compiler_

**Author:** Thor Whalen
**Date:** March 2026

---

## Abstract

Every modern CI system models pipelines as directed acyclic graphs, but GitHub Actions — the dominant CI platform — exposes this graph through untyped string outputs, manual three-step wiring ceremonies, and no compile-time validation of data flow. This paper surveys how five CI systems (Dagger, Tekton, Argo Workflows, Concourse, and GitHub Actions) represent, wire, parameterize, and validate pipeline DAGs, identifies the structural gap in GitHub Actions' design, and proposes `reci` — a Python tool that compiles declarative CI "recipes" into fully-wired GitHub Actions workflow YAML with compile-time data flow validation. The recipe format is a computational DAG where nodes are GitHub Actions with typed input/output contracts (introspected from `action.yml` metadata), edges represent data dependencies, and external parameters are injected from project config files via pluggable adapters. The compiler infers `needs:` edges, auto-generates the output forwarding boilerplate, validates the full graph (cycles, missing inputs, type compatibility), and produces workflow YAML — providing the developer experience of Dagger's typed pipelines on GitHub Actions' universal execution platform.

---

## 1. Introduction: CI Pipelines Are DAGs

A CI pipeline is a sequence of computational steps with data dependencies between them. A linting step depends on source code being checked out. A test step depends on dependencies being installed. A publish step depends on tests passing and a version number being computed. These dependencies form a directed acyclic graph (DAG), and every CI system — implicitly or explicitly — compiles a user's pipeline definition into one.

The five systems surveyed in this paper occupy distinct positions on the declarative-vs-programmatic spectrum. Dagger constructs DAGs implicitly through typed method chains in Python, Go, or TypeScript. Tekton and Argo Workflows declare them in Kubernetes-native YAML with explicit dependency fields. Concourse derives the graph implicitly from resource-flow constraints. GitHub Actions splits it across two tiers: a job-level DAG via `needs:` and sequential steps within each job. (See `@misc/docs/research/reci 01` for the full six-dimension comparison.)

Despite this convergence on DAGs as the computational model, GitHub Actions — the platform with the largest adoption — has the weakest support for the key properties that make DAGs useful: typed data flow, compile-time validation, and automatic wiring. The result is that developers write verbose, error-prone YAML where data-flow bugs (misspelled output names, missing cross-job forwarding, type coercion failures) surface only at runtime.

`reci` closes this gap. It is a Python package that takes a declarative *recipe* — a DAG of GitHub Action references — and compiles it into a complete workflow YAML file, auto-wiring inputs and outputs, injecting configuration from project files, and validating the entire graph before any YAML is generated.

---

## 2. Survey: How Five CI Systems Model Pipeline DAGs

### 2.1 DAG Representation

| System | DAG definition | Nodes | Edges | Parallelism |
|---|---|---|---|---|
| Dagger | Programmatic (SDK code) | API method calls | Implicit from method chaining | Engine-managed |
| Tekton | Declarative YAML (CRDs) | PipelineTasks | `runAfter` + result references | Tasks without deps run in parallel |
| Argo Workflows | Declarative YAML | DAG tasks | `dependencies` / `depends` fields | Tasks with satisfied deps run immediately |
| Concourse | Implicit from resources | Jobs | `passed:` constraints on `get` steps | Jobs without resource constraints run in parallel |
| GitHub Actions | Declarative YAML | Jobs | `needs:` field | Jobs without `needs:` run in parallel |

Dagger makes cycles structurally impossible through immutable builder patterns — each method call returns a new object, so the chain can only go forward [1]. Tekton creates edges two ways: `runAfter` for pure ordering, and `$(tasks.taskA.results.someResult)` references that automatically create data-dependency edges [3]. Argo's enhanced `depends` field supports status conditions like `A.Succeeded || A.Failed`, enabling sophisticated error-handling branches [4]. Concourse's `passed:` constraint is the most unusual approach — the DAG is *derived* from resource usage rather than declared explicitly [6]. GitHub Actions' `needs:` is the simplest model but operates only at the job level; within a job, steps are always sequential [7].

### 2.2 Data Flow

Every system grapples with the same question: how does output from Task A reach Task B?

**Dagger** uses typed artifact passing — data flows via first-class objects (`Container`, `Directory`, `File`, `Secret`) that are content-addressed and managed by the engine [8]. The type system prevents passing a `str` where a `Directory` is expected.

**Tekton** and **Argo** split data into small parameters (strings, ≤4 KB in Tekton) and large artifacts (files on shared volumes or object storage). Tekton's workspace-based sharing is a notorious footgun: workspaces do *not* create implicit DAG edges, requiring manual `runAfter` to avoid race conditions [9].

**GitHub Actions** requires a three-step ceremony for cross-job data flow: (1) write `key=value` to `$GITHUB_OUTPUT` in a step, (2) map step outputs to job-level `outputs:` in the job definition, (3) reference via `needs.<job>.outputs.<n>` in the consuming job [7]. All outputs are string-only with a 1 MB per-job limit. This ceremony is the primary boilerplate that reci eliminates. (See `@misc/docs/research/reci 02` for the complete technical reference on output wiring, including matrix output non-determinism, secret-masking gotchas, and the context availability table.)

### 2.3 Parameterization

| System | External parameter mechanism | Scope model |
|--------|------------------------------|-------------|
| Dagger | Function signatures + CLI args + `.env` files | Per-function |
| Tekton | Pipeline params → Task params (explicit mapping) | Two-level |
| Argo | Global `workflow.parameters` + template-level `inputs.parameters` | Global + per-template |
| Concourse | `((var))` interpolation + credential managers (Vault, CredHub) | Global, late-bound |
| GitHub Actions | `workflow_dispatch` inputs, `env`, `secrets`, `vars` contexts | Fragmented (5 namespaces) |

GitHub Actions has **no native mechanism** to inject values from a project config file like `pyproject.toml`. A step must explicitly read the file and write parsed values to `$GITHUB_OUTPUT`. This is the gap reci fills: reading project config at compile time and baking resolved values into the generated YAML.

### 2.4 Validation

| System | Validation timing | Cycle detection | Input validation | Type checking |
|--------|------------------|----------------|-----------------|---------------|
| Dagger | Dev time (mypy/pyright) + runtime (GraphQL schema) | Structurally impossible | Full (type system) | Full |
| Tekton | Admission webhook (Kahn's algorithm) | Yes | Param names/types | Partial |
| Argo | `argo lint` (offline) | Yes | Template references | Expression syntax only |
| Concourse | `fly validate-pipeline` (offline) | Yes | Structural only | No |
| GitHub Actions | Push time (syntax) + runtime (everything else) | Yes (`needs:`) | No | No |

The key insight: Dagger validates the most because its type system makes invalid pipelines unrepresentable. GitHub Actions validates the least because its output system is untyped strings. The third-party tool **actionlint** fills much of this gap with a full expression type system, action input/output verification, and deep semantic analysis — but it validates *existing* YAML, not the abstract data-flow graph. (See `@misc/docs/research/reci 03` for the full validation landscape including actionlint internals, the ESLint severity model, and the four-tier fixability taxonomy.)

### 2.5 The Impure Step Problem

Every system eventually delegates to opaque container commands, breaking whatever typed contract exists at the DAG level. Dagger's `Container.with_exec()` accepts `list[str]` and modifies the container filesystem opaquely [1]. Tekton Steps have arbitrary `script` fields [3]. Argo relies on containers writing output parameters to specific file paths, and missing files have historically crashed the workflow controller [4]. GitHub Actions' `run:` steps are entirely opaque — no declared inputs or outputs.

This is relevant to reci because `run:` steps violate the recipe's data-flow purity. The tool should flag them and suggest factoring them into composite actions with typed interfaces.

---

## 3. The Gap: GitHub Actions Lacks Typed Pipeline Compilation

Synthesizing the survey, GitHub Actions has the widest adoption but the weakest tooling for the properties that make CI-as-DAG useful:

| Property | Dagger | Tekton | Argo | GitHub Actions |
|----------|--------|--------|------|----------------|
| Typed data flow | ✅ Full type system | ✅ Param types | Partial | ❌ Strings only |
| Compile-time graph validation | ✅ Via host language | ✅ Admission webhook | ✅ `argo lint` | ❌ Runtime only |
| Auto-wired data dependencies | ✅ Implicit from types | ✅ From result references | ❌ Manual `dependencies:` | ❌ Manual `needs:` + ceremony |
| Config injection from project files | ✅ `.env` / CLI args | ✅ Pipeline params | ✅ Workflow params | ❌ Not supported |

**No existing Python library directly compiles a typed DAG of tasks into GitHub Actions YAML.** Strong building blocks exist — `graphlib.TopologicalSorter` for validation, Hamilton/pipefunc for DAG-from-signatures patterns, Pydantic for typed models — but they have never been assembled for this purpose.

---

## 4. `reci`: Design and Architecture

### 4.1 Core Concept: The Recipe

A recipe is a declarative YAML file that describes a CI pipeline as a computational DAG. Nodes are references to GitHub Actions (or inline shell commands). Edges are inferred from variable names: if action A declares an output called `version` and action B has an input called `version`, reci infers a data dependency. External inputs come from the project config file.

```yaml
name: CI
on: [push, pull_request]

jobs:
  validation:
    strategy:
      matrix:
        python-version: ${{ config.python_versions }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - uses: i2mint/wads/actions/install-deps@master
      - uses: i2mint/wads/actions/ruff-format@master
      - uses: i2mint/wads/actions/ruff-lint@master
      - uses: i2mint/wads/actions/run-tests@master

  publish:
    if: github.ref == 'refs/heads/main'
    needs: [validation]
    steps:
      - uses: i2mint/wads/actions/bump-version@master
        # outputs: new_version
      - uses: i2mint/wads/actions/build-dist@master
      - uses: i2mint/wads/actions/pypi-upload@master
      - uses: i2mint/wads/actions/git-tag@master
        # auto-wired: tag ← new_version (via name matching or explicit bind)
```

The recipe is structurally close to GitHub Actions YAML but **stripped of wiring boilerplate**: the `with:` blocks are mostly inferred from config and upstream outputs, the setup job is generated, and `${{ config.* }}` references are resolved at compile time.

### 4.2 Recipes as Computational DAGs

A recipe is not just an ordered step list — it is a computational DAG where nodes produce outputs that downstream nodes consume. The canonical example: a version-bumping step outputs `new_version`, and a release-tagging step needs that value as its `tag_name` input. This data dependency creates a DAG edge.

Each node in the DAG is represented as:

```
(input_names_mapping, action_spec, output_names)
```

Where `input_names_mapping` handles renaming (when action A outputs `new_version` but action B's input is `tag_name`), `action_spec` is the parsed `action.yml` contract, and `output_names` are the variables this node produces. Edges are inferred from name matching: if a node's output variable matches another node's input parameter, an edge is created.

The DAG has two kinds of input sources:

1. **Config values** — external parameters from the project config file, injected at compile time
2. **Upstream outputs** — values produced by earlier nodes in the DAG, wired at runtime via `${{ steps.<id>.outputs.<n> }}`

The compiler distinguishes these and generates different YAML for each: config values become `${{ needs.setup.outputs.<key> }}`, upstream outputs become `${{ steps.<id>.outputs.<n> }}`.

### 4.3 The Five Abstractions

**1. ActionSpec** — Parsed from an action's `action.yml`. Contains the input/output contract: name, required flag, default value, description. Fetched from GitHub (raw URL with API fallback) or declared manually in the recipe. For `run:` steps, inputs/outputs can be annotated in the recipe.

**2. RecipeGraph** — The computational DAG. Nodes are action steps (carrying `ActionSpec` + step ID + job grouping). Edges represent data flow: output-to-input wiring. External inputs come from config. Built on `graphlib.TopologicalSorter` for validation and parallel-wave scheduling.

**3. Config** — A flat `dict[str, Any]` with scoped overrides. Resolution order for input `root_dir` of action `run-tests`: (a) `run_tests__root_dir` in config (scoped override), (b) `root_dir` in config (shared default), (c) `default` from action.yml, (d) validation error if required. This flat-with-`__`-overrides namespace avoids nested config while handling name conflicts cleanly.

**4. ConfigAdapter** — A pluggable strategy (Protocol) for reading/writing config to/from files. Built-in adapters for `pyproject.toml` (via tomlkit), `package.json` (via json), `.ci.yml` (via ruamel.yaml). New adapters can be registered without modifying the core.

**5. Compiler** — Takes recipe + resolved action specs + resolved config → produces a complete GitHub Actions workflow YAML. The compiler: (a) injects a setup job that reads config and exports values as job outputs, (b) adds `needs:` edges inferred from data flow, (c) auto-generates the `with:` blocks mapping config/upstream outputs to action inputs, (d) auto-generates the cross-job output forwarding ceremony, (e) replaces `${{ config.* }}` with `${{ needs.setup.outputs.* }}`.

### 4.4 DAG Engine: graphlib + Custom RecipeGraph

The evaluation of DAG libraries (`@misc/docs/research/reci 04`) concluded:

- **`meshed.DAG`** is a poor fit — it requires Python callables as nodes, has single-output-per-node, no serialization, and no cycle detection. Creating dummy function stubs to satisfy meshed's signature introspection adds cost without value.
- **`meshed.itools`** contains useful standalone utilities (`topological_sort`, `edges`, `nodes`) on plain adjacency dicts, but lacks cycle detection — a dealbreaker.
- **`graphlib.TopologicalSorter`** (stdlib, Python 3.9+) is the strongest foundation — zero dependencies, built-in `CycleError`, parallel-wave scheduling via `get_ready()`/`done()`, any hashable as node.
- **NetworkX** is the upgrade path if reci later needs subgraph visualization, transitive reduction, or ancestor queries. Migration is low-cost.
- **Dask, Prefect, Hamilton** are execution-oriented frameworks requiring callables — architecturally wrong for a non-execution DAG compiler.

The recommended architecture: `graphlib.TopologicalSorter` + a custom `RecipeGraph` class (~200 lines):

```python
@dataclass(frozen=True)
class ActionNode:
    ref: str                           # "i2mint/wads/actions/run-tests@master"
    step_id: str
    job: str
    inputs: dict[str, InputSpec]       # from action.yml
    outputs: list[str]                 # from action.yml
    bind: dict[str, str] | None = None # input renaming: {action_input: dag_variable}

class RecipeGraph:
    _deps: dict[ActionNode, set[ActionNode]]
    _data_edges: dict[tuple[str, str], str]

    def execution_waves(self) -> list[tuple[ActionNode, ...]]:
        ts = TopologicalSorter(self._deps)
        ts.prepare()
        waves = []
        while ts.is_active():
            wave = ts.get_ready()
            waves.append(wave)
            ts.done(*wave)
        return waves

    def validate(self) -> ValidationReport:
        """Check cycles, missing inputs, duplicate outputs, purity."""
        ...
```

The `get_ready()`/`done()` protocol naturally maps to GitHub Actions job parallelism — each "wave" becomes a set of jobs that can run in parallel.

### 4.5 Data Flow Wiring

The compiler resolves each action input using a five-level precedence:

```
1. Explicit `with:` in recipe      → use verbatim
2. Upstream output name match       → wire ${{ steps.<id>.outputs.<n> }}
3. Config value (scoped then shared)→ wire ${{ needs.setup.outputs.<key> }}
4. Default from action.yml          → omit (GitHub uses the default)
5. None + required = true           → validation ERROR (FLOW001)
```

For cross-job output forwarding, the compiler auto-generates the three-step ceremony that GitHub Actions requires (step output → job output declaration → `needs` consumption). The user never writes this boilerplate.

Name matching normalizes to lowercase and treats hyphens as underscores (`new-version` matches `new_version`), consistent with GitHub Actions' runtime normalization [2].

**Key edge cases** the compiler must handle (from `@misc/docs/research/reci 02`):

- **Matrix outputs are non-deterministic**: last-to-finish wins. Emit `FLOW006` warning.
- **Unset outputs evaluate to empty string** (not null, not error). No way to distinguish "skipped step" from "step ran but didn't produce output."
- **Type coercion**: all outputs are strings. `"false"` as a boolean input throws a type error. Inject `== 'true'` comparisons for boolean-typed inputs.
- **Context availability**: `steps` context is NOT available in `jobs.<id>.if`, `jobs.<id>.runs-on`, or `jobs.<id>.strategy`. The compiler must validate injection points.
- **Secret masking**: if an output value matches a secret substring, it is silently dropped with a warning in logs.
- **Size limits**: 1 MB per job (all outputs), 50 MB per workflow run.

### 4.6 Validation System

reci's validator uses ESLint-style configurable severity (`off`/`warn`/`error`) with ruff-style prefix-based rule grouping and the plain dataclass pattern (no framework dependency). See `@misc/docs/research/reci 03` for the full design rationale.

#### Rule catalog

| Rule ID | Category | Default | Description |
|---------|----------|---------|-------------|
| `DAG001` | Structure | error | Cycle detected in recipe DAG |
| `DAG002` | Structure | error | Duplicate output name (two nodes produce same variable) |
| `DAG003` | Structure | error | Steps not in topological order |
| `DAG004` | Structure | warning | Isolated node (no inputs or outputs connected) |
| `FLOW001` | Data flow | error | Required input has no source (config, upstream output, or default) |
| `FLOW002` | Data flow | warning | Input name matches multiple upstream outputs (ambiguous) |
| `FLOW003` | Data flow | info | Input resolved from action.yml default |
| `FLOW004` | Data flow | warning | Output declared but never consumed downstream |
| `FLOW005` | Data flow | warning | String output wired to boolean-typed input (coercion risk) |
| `FLOW006` | Data flow | warning | Matrix job output consumed downstream (non-deterministic) |
| `CONF001` | Config | error | Required config key missing from config file |
| `CONF002` | Config | warning | Optional config key missing (using default) |
| `CONF003` | Config | info | Config key present but unused by any action |
| `PURE001` | Purity | warning | `run:` step detected — breaks typed data-flow contract |
| `PURE002` | Purity | info | `run:` step writes to `$GITHUB_OUTPUT` — consider factoring into action |
| `PURE003` | Purity | warning | `if:` conditional on step — consider pattern alternatives |
| `ACT001` | Action | warning | `required: true` in action.yml not enforced at runtime |
| `ACT002` | Action | error | Referenced action not found (fetch failed) |
| `ACT003` | Action | info | Action output not declared in action.yml |

#### Architecture

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

@dataclass
class ValidationReport:
    findings: list[Finding]

    @property
    def has_errors(self) -> bool:
        return any(f.severity == Severity.ERROR for f in self.findings)
```

Rules are composable functions that take `RecipeGraph` + `Config` and yield `Finding` objects. Severity is configurable per-rule via `.reci.yml`. The `--max-warnings N` pattern from ESLint enables gradual adoption.

Output formats: human-readable CLI (rustc-style), JSON, GitHub Actions annotations, SARIF.

#### Four-tier fixability taxonomy

| Tier | Label | Example | Applied with |
|------|-------|---------|-------------|
| 1 | Safe auto-fix | Add missing config key with known default | `--fix` |
| 2 | Unsafe auto-fix | Reorder steps for topological correctness | `--fix --unsafe-fixes` |
| 3 | Suggested fix | Rewrite `run:` step as composite action | Shown, user applies |
| 4 | Human judgment | Whether `needs:` dependencies reflect correct graph | Flagged only |

### 4.7 The Impure Step Problem

`run:` steps are the escape hatch from the typed DAG. reci handles them with three tiers:

1. **Detect and classify.** Parse `run:` blocks for `${{ }}` references (implicit inputs) and `>> $GITHUB_OUTPUT` patterns (implicit outputs). Report as `PURE001`/`PURE002`.

2. **Suggest refactoring.** When a `run:` step has detectable I/O, suggest factoring into a composite action. Provide Claude skills for this transformation.

3. **Allow manual declaration.** Annotate `run:` steps with explicit I/O in the recipe:

```yaml
- id: custom_step
  run: echo "version=$(cat VERSION)" >> $GITHUB_OUTPUT
  outputs: [version]  # reci annotation — makes this node analyzable
```

Conditional execution (`if:` on steps/jobs) is modeled as a node annotation, not a DAG structural element. The validator flags conditionals (`PURE003`) and suggests alternative patterns, but doesn't refuse them.

### 4.8 Config Adapters

```python
class ConfigAdapter(Protocol):
    def read(self, path: str) -> dict[str, Any]: ...
    def write(self, path: str, config: dict[str, Any]) -> None: ...
    def default_path(self) -> str: ...
```

| Adapter | File | Library | Notes |
|---------|------|---------|-------|
| `PyprojectTomlAdapter` | `pyproject.toml` | tomlkit | Reads `[tool.ci]`, round-trip preserving comments |
| `WadsAdapter` | `pyproject.toml` | tomlkit | Reads `[tool.wads.ci]`, backward compat |
| `PackageJsonAdapter` | `package.json` | json (stdlib) | Reads `"ci"` key, preserves indent |
| `YamlAdapter` | `.ci.yml` | ruamel.yaml | Full file read/write |

Adapter selection: (1) explicit CLI flag, (2) ecosystem marker detection, (3) `.reci.yml` project config. The adapter is registerable/pluggable — users can provide custom adapters for their own config conventions (e.g., a wads-compatible adapter that reads the existing `[tool.wads.ci]` structure).

### 4.9 YAML Generation

**ruamel.yaml** is the only viable Python library for GitHub Actions YAML. PyYAML (YAML 1.1) treats `on` as boolean `True`. ruamel.yaml (YAML 1.2) handles this correctly, preserves comments/style for round-tripping, and supports explicit quoting for `${{ }}` expressions.

The compiler builds the workflow as a Python dict and serializes with ruamel.yaml — no Jinja2 templates. More testable, avoids indentation bugs, allows programmatic manipulation before serialization.

### 4.10 CLI Interface

```
reci compile <recipe> [--config-adapter pyproject] [--output .github/workflows/ci.yml]
reci validate [--config-adapter pyproject] [--recipe recipe.yml]
reci scaffold <recipe> [--config-adapter pyproject]
reci inspect <action-ref>
```

Uses `argh` for dispatch.

---

## 5. Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DAG engine | `graphlib.TopologicalSorter` (stdlib) | Zero deps, `CycleError`, parallel waves, any hashable as node |
| Not meshed.DAG | — | Requires callables as nodes; wrong abstraction for CI action specs |
| Config shape | Flat dict with `__` overrides | SSOT for shared params; no nesting depth; simple two-level lookup |
| Config I/O | Pluggable adapter (Protocol) | Multiple ecosystems; backward-compat with wads; extensible |
| YAML library | ruamel.yaml | YAML 1.2 (`on` key), comment preservation, style control |
| TOML library | tomlkit | Only round-trip TOML editor preserving comments/formatting |
| Validation model | ESLint-style severity (off/warn/error) | Three levels needed; `--max-warnings N` for gradual adoption |
| Rule extensibility | Flake8-style entry points + ruff-style prefix groups | Plugin discovery; category-level enable/disable |
| actionlint | Subprocess, not reimplementation | 14 check categories; multi-year effort to reimplement |
| TS config patching | Don't — generate fresh or tell user | magicast is Node-only; config is simple enough to regenerate |

---

## 6. Implementation Plan

### 6.1 Package structure

```
reci/
├── __init__.py
├── __main__.py          # CLI dispatch via argh
├── action_spec.py       # ActionSpec: parse action.yml, fetch from GitHub
├── recipe.py            # Recipe: parse recipe YAML, build RecipeGraph
├── graph.py             # RecipeGraph: DAG structure, validation, wave computation
├── compiler.py          # Compiler: recipe + config → workflow YAML
├── config.py            # Config resolution: flat dict + __ overrides
├── adapters/
│   ├── __init__.py
│   ├── base.py          # ConfigAdapter Protocol
│   ├── pyproject.py     # PyprojectTomlAdapter (tomlkit)
│   ├── wads.py          # WadsAdapter (backward compat)
│   ├── package_json.py  # PackageJsonAdapter (json)
│   └── yaml_adapter.py  # YamlAdapter (ruamel.yaml)
├── validation/
│   ├── __init__.py
│   ├── report.py        # Finding, ValidationReport, Severity
│   ├── rules/
│   │   ├── dag.py       # DAG001–DAG004
│   │   ├── flow.py      # FLOW001–FLOW006
│   │   ├── config.py    # CONF001–CONF003
│   │   ├── purity.py    # PURE001–PURE003
│   │   └── action.py    # ACT001–ACT003
│   └── formatters.py    # CLI, JSON, GitHub annotations, SARIF
└── yaml_gen.py          # ruamel.yaml wrapper for GH Actions YAML
```

### 6.2 Dependencies

| Package | Purpose |
|---------|---------|
| `ruamel.yaml` | Parse action.yml, generate CI YAML (YAML 1.2, handles `on:`) |
| `tomlkit` | Round-trip edit pyproject.toml (comment preservation) |
| `argh` | CLI dispatch |
| `httpx` | Fetch action.yml from GitHub |

### 6.3 Phases

**Phase 1 — Core loop.** ActionSpec parsing, RecipeGraph construction, Compiler producing valid YAML. Acceptance: compile Python library recipe into working CI YAML.

**Phase 2 — DAG data flow.** Output-to-input wiring by name matching. Cross-step output forwarding within a job. Acceptance: bump-version output wired to git-tag input.

**Phase 3 — Validation.** Full rule set (DAG, FLOW, CONF, PURE, ACT). Acceptance: detect missing config, detect cycle, detect ambiguous wiring.

**Phase 4 — Config adapters.** PyprojectTomlAdapter, PackageJsonAdapter. Acceptance: round-trip pyproject.toml without destruction.

**Phase 5 — Cross-job wiring.** Auto-generate three-step output forwarding ceremony. Two-level DAG (jobs containing steps). Matrix output warnings.

**Phase 6 — CLI + formats.** `reci compile`, `validate`, `scaffold`, `inspect`. Multiple output formats.

---

## 7. Relationship to Existing Work

### 7.1 wads/isee: The Pattern Being Generalized

The i2mint Python CI system (wads + isee) implements a three-layer architecture: static workflow template + reusable composite actions + per-project config in `pyproject.toml`. (See `@misc/docs/wads_ci_architecture_analysis.md`.) reci generalizes this: recipes replace static templates, data flow is modeled and validated, and pluggable config adapters support multiple ecosystems. reci is designed as an independent tool that, once stable, could replace wads' CI generation components.

### 7.2 No Existing Tool Does This

| Tool | Why it's not reci |
|------|-------------------|
| Dagger | Replaces GitHub Actions entirely; not composable with existing actions |
| Tekton/Argo | Different execution platform (Kubernetes) |
| Projen | High lock-in; generated files read-only; no recipe/DAG concept |
| Nx/Turborepo | Local task orchestration; no CI YAML generation |
| Cookiecutter/Copier | One-shot scaffolding; no ongoing validation or data-flow analysis |
| actionlint | Validates existing YAML; doesn't operate on abstract data-flow graphs |

reci occupies a unique position: it operates at the *recipe level* — above individual workflow YAML but below a full CI platform — and compiles down to GitHub Actions while providing Dagger-level data-flow validation.

---

## 8. Supporting Documents

The following documents in `@misc/docs/` provide detailed research backing each design decision:

| Document | Contents |
|----------|----------|
| `research/reci 01` | Six-dimension comparison of Dagger, Tekton, Argo, Concourse, GitHub Actions as DAG systems |
| `research/reci 02` | Complete GitHub Actions output wiring reference: step/job outputs, matrix gotchas, context availability, size limits |
| `research/reci 03` | Validation tool survey: actionlint internals, ESLint severity model, Python validation patterns, fixability taxonomy |
| `research/reci 04` | meshed DAG API evaluation: why graphlib wins, dependency comparison table, RecipeGraph design |
| `wads_ci_architecture_analysis.md` | How wads CI works today: three-layer architecture, design tensions, what to generalize |
| `claude_code_prompt.md` | Implementation prompt with acceptance tests and CLI specification |

---

## References

[1] Dagger Documentation, "Programmable Pipelines," https://docs.dagger.io/features/programmable-pipelines/

[2] GitHub Docs, "Metadata syntax for GitHub Actions," https://docs.github.com/en/actions/creating-actions/metadata-syntax-for-github-actions

[3] Tekton Documentation, "Pipelines," https://tekton.dev/docs/pipelines/pipelines/

[4] Argo Workflows Documentation, "DAG Template," https://argo-workflows.readthedocs.io/en/latest/walk-through/dag/

[5] Argo Workflows GitHub, "DAG proposal discussion," https://github.com/argoproj/argo-workflows/issues/625

[6] Concourse CI Documentation, "Pipeline Mechanics," https://concourse-ci.org/pipelines.html

[7] GitHub Docs, "Workflow syntax for GitHub Actions," https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions

[8] Dagger Documentation, "Core Types," https://docs.dagger.io/getting-started/types/

[9] Tekton Documentation, "Workspaces," https://tekton.dev/docs/pipelines/workspaces/

[10] Dagger Documentation, "Secrets Integration," https://docs.dagger.io/features/secrets/

[11] rhysd, "actionlint," https://github.com/rhysd/actionlint

[12] Python Documentation, "graphlib," https://docs.python.org/3/library/graphlib.html

[13] NetworkX, "Directed Acyclic Graphs," https://networkx.org/documentation/stable/reference/algorithms/dag.html

[14] Apache Hamilton, https://github.com/apache/hamilton

[15] pipefunc, https://github.com/pipefunc/pipefunc

[16] SchemaStore, "GitHub Workflow JSON Schema," https://json.schemastore.org/github-workflow.json

[17] OASIS, "SARIF v2.1.0," https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html

[18] ESLint, "Configuring Rules," https://eslint.org/docs/latest/use/configure/rules

[19] Astral Software, "Ruff," https://docs.astral.sh/ruff/

[20] python-poetry/tomlkit, https://github.com/python-poetry/tomlkit

[21] ruamel.yaml, https://pypi.org/project/ruamel.yaml/

[22] i2mint/wads, https://github.com/i2mint/wads

[23] i2mint/isee, https://github.com/i2mint/isee

[24] i2mint/meshed, https://github.com/i2mint/meshed
