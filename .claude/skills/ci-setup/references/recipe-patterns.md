# Recipe Patterns

Common reci recipe patterns organized by project type. Use these as starting points and adapt to the user's project.

## Table of contents

- [Python package (pip)](#python-package-pip)
- [Python package (uv)](#python-package-uv)
- [Node.js / TypeScript](#nodejs--typescript)
- [Common job patterns](#common-job-patterns)

---

## Python package (pip)

Basic test + publish pipeline for a pip-installable Python package.

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
          python-version: '${{ matrix.python-version }}'
      - run: pip install -e ".[dev]"
      - run: ruff format --check .
      - run: ruff check .
      - run: pytest --doctest-modules

  publish:
    needs: [test]
    if: github.ref == 'refs/heads/main'
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install build twine
      - run: python -m build
      - run: twine upload dist/*
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: '${{ secrets.PYPI_PASSWORD }}'
```

Config (`[tool.ci]` in pyproject.toml):
```toml
[tool.ci]
python_versions = ["3.10", "3.12"]
```

---

## Python package (uv)

Same pipeline but using `uv` for faster installs and `astral-sh/setup-uv`.

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
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - run: |
          uv python install ${{ matrix.python-version }}
          uv venv --python ${{ matrix.python-version }}
      - run: |
          source .venv/bin/activate
          uv pip install -e ".[dev]"
      - run: uvx ruff format --check .
      - run: uvx ruff check .
      - run: |
          source .venv/bin/activate
          pytest --doctest-modules

  publish:
    needs: [test]
    if: github.ref == 'refs/heads/main'
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v5
      - run: uv build
      - run: uv publish dist/*
        env:
          UV_PUBLISH_TOKEN: '${{ secrets.PYPI_PASSWORD }}'
```

---

## Node.js / TypeScript

Basic lint + test + build for a Node.js project.

```yaml
name: CI
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        node-version: [18, 20, 22]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '${{ matrix.node-version }}'
          cache: npm
      - run: npm ci
      - run: npm run lint
      - run: npm test

  build:
    needs: [test]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: npm
      - run: npm ci
      - run: npm run build

  publish:
    needs: [build]
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          registry-url: 'https://registry.npmjs.org'
      - run: npm ci
      - run: npm publish
        env:
          NODE_AUTH_TOKEN: '${{ secrets.NPM_TOKEN }}'
```

---

## Common job patterns

### Version bump (i2mint/isee)

```yaml
- id: bump
  uses: i2mint/isee/actions/bump-version-number@master
```

Outputs: `version` (the new version string).

### Git commit + tag (i2mint/wads)

```yaml
- uses: i2mint/wads/actions/git-commit@master
  with:
    commit-message: "Release ${{ env.VERSION }} [skip ci]"
    ssh-private-key: '${{ secrets.SSH_PRIVATE_KEY }}'
    push: true

- uses: i2mint/wads/actions/git-tag@master
  with:
    tag: '${{ env.VERSION }}'
    message: "Release ${{ env.VERSION }}"
    push: true
```

### GitHub Pages (epythet)

```yaml
github-pages:
  needs: [publish]
  permissions:
    contents: write
    pages: write
    id-token: write
  if: github.ref == format('refs/heads/{0}', github.event.repository.default_branch)
  steps:
    - uses: i2mint/epythet/actions/publish-github-pages@master
      with:
        github-token: '${{ secrets.GITHUB_TOKEN }}'
        ignore: "tests/,scrap/,examples/"
```

### Read CI config from pyproject.toml (wads)

```yaml
- uses: i2mint/wads/actions/read-ci-config@master
  id: config
  with:
    pyproject-path: .
```

### Windows testing (optional)

```yaml
windows-test:
  if: needs.setup.outputs.test-on-windows == 'true'
  runs-on: windows-latest
  continue-on-error: true
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: '3.12'
    - run: pip install -e ".[dev]"
    - run: pytest
```
