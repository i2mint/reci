# CI Scenarios

Guidance on what CI makes sense for different kinds of projects. Use this to inform your recommendations.

## Table of contents

- [Python library (public, on PyPI)](#python-library-public-on-pypi)
- [Python application (internal/deployed)](#python-application-internaldeployed)
- [Monorepo with multiple packages](#monorepo-with-multiple-packages)
- [Node.js / TypeScript project](#nodejs--typescript-project)
- [Data science / ML project](#data-science--ml-project)
- [Small personal project](#small-personal-project)

---

## Python library (public, on PyPI)

**Must-haves:**
- Lint + format check (ruff)
- Tests across multiple Python versions (at minimum: oldest supported + latest)
- Doctest modules (catches stale examples in docstrings)
- Auto-publish to PyPI on main branch push
- Version bumping (manual or auto)

**Nice-to-haves:**
- Coverage reporting (don't enforce threshold initially — track trend)
- Windows testing (if the library might run on Windows)
- Docs auto-publish to GitHub Pages
- Code metrics tracking

**Secrets needed:** `PYPI_PASSWORD` (API token), `SSH_PRIVATE_KEY` (for push-back commits)

**Common actions:** `actions/checkout`, `actions/setup-python` (or `astral-sh/setup-uv`), `i2mint/isee/actions/bump-version-number`, `i2mint/wads/actions/git-commit`, `i2mint/wads/actions/git-tag`, `i2mint/epythet/actions/publish-github-pages`

---

## Python application (internal/deployed)

**Must-haves:**
- Lint + format check
- Tests (usually single Python version — whatever runs in production)
- Build/deploy step triggered on main

**Nice-to-haves:**
- Docker build + push
- Deploy to staging on PR merge, production on tag
- Integration/smoke tests post-deploy
- Environment-specific config validation

**Key difference from library:** No PyPI publish. Instead, deploy to infrastructure (Docker registry, cloud service, etc.).

---

## Monorepo with multiple packages

**Approach:** Use path filters on triggers so each package only runs CI when its files change.

```yaml
on:
  push:
    paths:
      - 'packages/core/**'
```

Or use a single workflow with conditional jobs. reci's config system can help parameterize per-package settings.

**Considerations:**
- Shared dependencies between packages — do you test downstream when upstream changes?
- Build order matters if packages depend on each other
- Matrix over packages vs. separate workflows (tradeoff: simplicity vs. isolation)

---

## Node.js / TypeScript project

**Must-haves:**
- `npm ci` (deterministic installs from lockfile)
- Lint (eslint/biome)
- Tests (jest/vitest)
- Build step (TypeScript compile, bundler)

**Nice-to-haves:**
- Preview deployments on PRs (Vercel, Netlify)
- Lighthouse CI for web apps
- Bundle size tracking
- E2E tests (Playwright, Cypress)

**Common actions:** `actions/setup-node` (with `cache: npm`), `actions/upload-artifact`

---

## Data science / ML project

**Must-haves:**
- Lint + format check (ruff)
- Unit tests for data processing functions
- Notebook execution check (papermill or nbconvert)

**Nice-to-haves:**
- Model validation tests (accuracy thresholds)
- Data validation (great-expectations or pandera)
- DVC pipeline trigger
- GPU testing (self-hosted runner or specialized service)

**Considerations:**
- Large data files — use DVC or LFS, don't download full datasets in CI
- Long-running training — separate "quick check" CI from "full training" CI
- Reproducibility — pin random seeds, track model artifacts

---

## Small personal project

**Keep it minimal.** CI shouldn't be more complex than the project itself.

**Recommended:** A single job that lints and tests:

```yaml
name: CI
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -e ".[dev]"
      - run: pytest
```

Add publishing later when the project matures. Don't start with 5 jobs and a matrix strategy for a weekend script.
