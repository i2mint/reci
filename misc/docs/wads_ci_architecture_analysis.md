# How wads CI Works: Architecture Analysis

## The Core Pattern

Wads implements a **config-driven, composable CI system** for Python projects. The key insight is separating three concerns:

1. **The workflow template** (static, identical across all projects)
2. **Reusable composite actions** (the "functions" of CI)
3. **Per-project configuration** (lives in `pyproject.toml`)

```
pyproject.toml          github_ci_publish_2025.yml         actions/
[tool.wads.ci.*]   -->  reads config, passes to     -->    read-ci-config/
                        reusable composite actions         install-deps/
                                                           run-tests/
                                                           ruff-format/
                                                           ruff-lint/
                                                           build-dist/
                                                           pypi-upload/
                                                           git-commit/
                                                           git-tag/
```

## How It Works Step by Step

### 1. The Workflow Template (the "main()")

`github_ci_publish_2025.yml` is a **fixed template** copied identically into every project. It never contains project-specific values. It defines 4-5 jobs:

- **setup** - Reads `[tool.wads.ci]` from `pyproject.toml`, exports as job outputs
- **validation** - Matrix-tests across Python versions: install deps, lint, format, test
- **windows-validation** (optional) - Same on Windows, `continue-on-error: true`
- **publish** (main/master only) - Format, bump version, build, upload to PyPI, commit, tag
- **github-pages** (optional) - Publish docs

### 2. Composite Actions (the "functions")

Each action lives in `i2mint/wads/actions/<name>/action.yml` and acts like a function:

| Action | Inputs | What it does |
|--------|--------|-------------|
| `read-ci-config` | `pyproject-path` | Parses `[tool.wads.ci]` sections, exports as outputs |
| `install-system-deps` | `pyproject-path` | Reads `[tool.wads.ops.*]`, runs OS-level installs |
| `install-deps` | `dependency-files`, `extras` | `pip install` from pyproject.toml/requirements.txt |
| `ruff-format` | `line-length`, `target-path` | Run Ruff formatter |
| `ruff-lint` | `root-dir`, `output-format` | Run Ruff linter |
| `run-tests` | `root-dir`, `exclude`, `coverage`, `pytest-args` | Run pytest with doctests + coverage |
| `build-dist` | `sdist`, `wheel` | Build wheel and/or sdist |
| `pypi-upload` | `pypi-username`, `pypi-password` | Upload to PyPI |
| `git-commit` | `commit-message`, `ssh-private-key`, `push` | Commit + push (SSH) |
| `git-tag` | `tag`, `message`, `push` | Create + push git tag |

The actions are called with `uses: i2mint/wads/actions/<name>@master`.

### 3. Per-Project Configuration (the "arguments")

All project-specific config lives under `[tool.wads.ci]` in `pyproject.toml`:

```toml
[tool.wads.ci.testing]
python_versions = ["3.10", "3.12"]
pytest_args = ["-v", "--tb=short"]
coverage_enabled = true
test_on_windows = true

[tool.wads.ci.env]
required_envvars = ["API_KEY"]
defaults = {"LOG_LEVEL" = "DEBUG"}

[tool.wads.ci.build]
sdist = true
wheel = true
```

The **setup** job reads this config and passes values as outputs to downstream jobs, which pass them as inputs to composite actions.

---

## Design Tensions and Trade-offs

### PROS of the wads approach

**1. Write once, use everywhere**
One workflow file across dozens of projects. A new project gets CI for free by running `populate`. No copy-paste, no drift.

**2. Config-driven customization**
Adding Windows testing or changing Python versions = edit one TOML section. No YAML surgery.

**3. Composability**
Actions are independently testable, versionable units. You can swap `ruff-lint` for a different linter action without touching anything else.

**4. Progressive disclosure**
Zero-config works (sensible defaults). Power users can override every detail via `[tool.wads.ci.*]`.

**5. Centralized updates**
Fix a bug in `run-tests/action.yml` once, all projects get the fix (they reference `@master`).

### CONS and tensions

**1. SSOT creates mixed concerns**
`pyproject.toml` is the packaging config. Cramming CI config into `[tool.wads.ci]` means:
- Packaging tools don't understand these sections (they're in a `[tool.*]` namespace, so at least they don't break anything)
- CI-only settings (Windows testing, metrics) sit next to package metadata
- Someone reading `pyproject.toml` has to mentally separate "this is for pip" from "this is for CI"

The counter-argument: the SSOT benefit is real. Python version constraints, test paths, and dependency extras ARE shared between packaging and CI. Splitting them risks drift.

**2. Indirection makes debugging harder**
When CI fails, you're debugging through: workflow YAML -> composite action YAML -> shell scripts -> Python scripts. Three levels of indirection.

**3. `@master` pinning is fragile**
All projects point to `@master`. A breaking change in an action breaks every project simultaneously. Semantic versioning (`@v2`) would be safer but adds maintenance burden.

**4. Config reading requires installing wads in CI**
The `read-ci-config` action installs wads itself (`pip install wads>=0.1.48`) just to parse the config. This is a bootstrap dependency.

**5. Custom logic is hard to express**
TOML config works for flags and lists, but if a project needs conditional logic ("only run E2E tests on main", "use different test commands for different Python versions"), you either need to extend the config schema or drop down to raw YAML.

---

## The Key Architectural Insight

The pattern wads implements is essentially:

```
Static Orchestrator + Reusable Functions + External Config = Scalable CI
```

This is analogous to:
- A **main()** that reads a config file and calls library functions
- A **Makefile** that includes shared `.mk` fragments
- A **Terraform** module that takes variables

The design question for any ecosystem is: **where does the config live, and how do the reusable pieces get distributed?**

| Concern | wads/Python answer | Frontend question |
|---------|-------------------|-------------------|
| Config location | `pyproject.toml` (SSOT with packaging) | `package.json`? Separate file? |
| Config format | TOML under `[tool.wads.ci]` | JSON? YAML? JS/TS config? |
| Reusable units | GitHub composite actions | GH actions? npm scripts? Turborepo tasks? |
| Distribution | `uses: org/repo/actions/X@ref` | Same? npm packages? |
| Orchestrator | Static workflow YAML template | Same? But different jobs (build, typecheck, E2E...) |
| Package registry | PyPI | npm |
| Build step | `hatchling` (simple) | Vite/Next/esbuild (complex, framework-dependent) |
| Linting | Ruff (one tool) | ESLint + Prettier (or Biome) |
| Type checking | Optional (mypy) | Essential (TypeScript) |

The frontend ecosystem is more fragmented, which makes the "one static template" harder -- but not impossible.
