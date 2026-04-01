---
name: ci-setup
description: >
  Create a new CI/CD pipeline for a project using reci recipes.
  Use this skill whenever the user wants to set up CI, create a GitHub Actions workflow,
  add continuous integration to their project, or says things like "make a CI setup for me",
  "set up CI", "add CI/CD", "create a workflow", or "I need GitHub Actions for this project".
  Also trigger when the user asks about setting up testing, linting, publishing, or deployment
  pipelines — even if they don't mention "reci" or "CI" explicitly.
---

# CI Setup with reci

Help the user create a CI/CD pipeline for their project by generating a reci recipe and compiling it into a GitHub Actions workflow.

## Workflow

### 1. Understand the project

Before writing anything, examine the user's project to understand what kind of CI makes sense.

**Read these files** (whichever exist):
- `pyproject.toml` or `setup.cfg` or `setup.py` — Python project metadata, dependencies, existing tool config
- `package.json` — Node/JS project metadata
- `.github/workflows/*.yml` — any existing workflows (if they exist, suggest the ci-migrate skill instead)
- `Makefile`, `justfile`, `Taskfile.yml` — existing task runners
- Source directory structure — figure out the language, framework, test setup

**Determine:**
- Language and ecosystem (Python, JS/TS, Rust, Go, etc.)
- Package manager (pip/uv/poetry, npm/yarn/pnpm, cargo, etc.)
- Test framework (pytest, jest, go test, etc.)
- Linting/formatting tools already configured (ruff, eslint, prettier, etc.)
- Whether it publishes to a registry (PyPI, npm, crates.io)
- Whether it has documentation to build/publish

### 2. Propose a plan

Present the user with a concise summary of what you found and what CI jobs you recommend. Something like:

> I see a Python package using pytest and ruff, publishing to PyPI. Here's what I'd set up:
> - **test**: lint + test across Python 3.10, 3.12
> - **publish**: version bump, build, publish to PyPI (on main branch push)
> - **docs**: publish to GitHub Pages (if they have sphinx/epythet docs)
>
> Does this look right? Anything you'd add or remove?

Wait for confirmation before writing files.

### 3. Write the recipe

Create a `recipe.yml` (or whatever name the user prefers) in the project root. The recipe uses reci's extended YAML format:

```yaml
name: CI
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ${{ fromJson(needs.setup.outputs.python_versions) }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '${{ config.python_version }}'
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: pytest

  publish:
    needs: [test]
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      # ... publishing steps
```

Key reci features to use:
- **`${{ config.X }}`** for values that come from project config (python versions, project name, etc.)
- **`bind:`** when an upstream step's output name doesn't match a downstream input name
- **`outputs:`** on `run:` steps to declare what they produce

Refer to `references/recipe-patterns.md` for common recipe patterns by project type.

### 4. Set up config

Add a `[tool.ci]` section to `pyproject.toml` (or the appropriate config source) with the values the recipe references. Use `reci scaffold recipe.yml` to discover required config keys if unsure.

### 5. Compile and validate

```bash
# Validate the recipe
reci validate --recipe recipe.yml

# Compile to workflow YAML
reci compile recipe.yml --output .github/workflows/ci.yml
```

If validation reports errors, fix them. Show the user the compiled workflow and explain what reci auto-generated (the setup job, cross-job wiring, needs edges).

### 6. Explain what to do next

Tell the user:
- What secrets they need to configure (e.g., `PYPI_PASSWORD`, `SSH_PRIVATE_KEY`)
- How to customize the recipe later (edit `recipe.yml`, recompile)
- How `reci validate` catches problems before they hit CI

## Important notes

- Always propose before writing. Don't dump a 200-line workflow without the user's buy-in.
- Keep recipes minimal. Start with what the project actually needs, not every possible CI job.
- If the project already has `.github/workflows/` files, suggest the **ci-migrate** skill instead of overwriting.
- The compiled workflow is the output artifact — the recipe is the source of truth. Make sure the user understands this.
