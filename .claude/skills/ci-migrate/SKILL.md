---
name: ci-migrate
description: >
  Migrate an existing GitHub Actions workflow to a reci recipe.
  Use this skill when the user wants to convert their current CI workflow to reci,
  says things like "migrate my CI to reci", "convert my workflow to a recipe",
  "refactor my GitHub Actions", or "I want to use reci for my existing CI".
  Also trigger when the user has an existing .github/workflows/ directory and asks
  about reci — they probably want a migration, not a fresh setup.
---

# CI Migration to reci

Help the user convert an existing GitHub Actions workflow into a reci recipe, preserving behavior while gaining reci's benefits (declarative config, auto-wiring, validation).

## Workflow

### 1. Read the existing workflow

Read all files in `.github/workflows/`. Understand:
- What jobs exist and their dependency graph (`needs:`)
- What actions are used (`uses:`) and what inputs they receive (`with:`)
- What `run:` steps do and what outputs they produce
- How values flow between jobs (the `outputs:` / `needs.X.outputs.Y` ceremony)
- What config is hardcoded vs. parameterized
- What secrets and environment variables are used
- Conditional execution (`if:` expressions)

### 2. Identify what reci can simplify

Point out to the user what reci will clean up:

- **Cross-job output wiring**: All the boilerplate where job A declares `outputs:` that forward `steps.X.outputs.Y`, and job B reads `needs.A.outputs.Y` — reci generates this automatically.
- **Config injection**: Hardcoded values (python versions, project name, pytest args) that should live in `pyproject.toml` — reci's `${{ config.* }}` references handle this.
- **Input/output name mismatches**: Cases where `bind:` would be cleaner than manual expression wiring.
- **Setup job**: If the workflow has a setup/config-reading job, reci can auto-generate it.

Also flag things reci **doesn't** handle that will stay as-is:
- Complex `run:` scripts (reci passes these through, but they're untyped)
- Matrix strategies (supported, but remain in the recipe)
- Secrets (referenced the same way, but reci doesn't manage them)

### 3. Present the migration plan

Show the user a summary:

> Your workflow has 4 jobs: setup, test, publish, docs.
>
> **What reci simplifies:**
> - The setup job (28 lines) → auto-generated from config
> - Cross-job output wiring in test/publish (15 lines of boilerplate) → automatic
> - 6 hardcoded values → `${{ config.* }}` references
>
> **What stays the same:**
> - The test `run:` script (complex pytest invocation)
> - Matrix strategy for python versions
> - Secret references
>
> **Recipe will be ~40 lines vs. the current ~180 lines.**

Wait for the user to confirm before writing the recipe.

### 4. Write the recipe

Translate the workflow into a reci recipe:

1. **Remove the setup/config job** — reci generates it. Move hardcoded values into `[tool.ci]` config.
2. **Strip cross-job output forwarding** — just use the action outputs directly; reci wires them.
3. **Replace hardcoded values** with `${{ config.X }}` references.
4. **Add `bind:` mappings** where upstream output names don't match downstream input names.
5. **Add `outputs:`** to `run:` steps that write to `$GITHUB_OUTPUT`.
6. **Simplify `needs:`** — keep explicit ordering constraints, but data-flow `needs` will be auto-inferred.
7. **Preserve `if:`, `strategy:`, `permissions:`, `env:`** — these pass through to the compiled output.

### 5. Set up config

Extract hardcoded values into the config source. Suggest `[tool.ci]` in `pyproject.toml` for Python projects:

```toml
[tool.ci]
python_versions = ["3.10", "3.12"]
project_name = "mypackage"
pytest_args = "-v --tb=short"
```

### 6. Compile and compare

```bash
reci validate --recipe recipe.yml
reci compile recipe.yml --output .github/workflows/ci.yml
```

Show a diff between the original workflow and the compiled output. The compiled version should be functionally equivalent (or the user should understand any differences). Key things to check:
- Same jobs, same ordering
- Same action versions
- Same conditional logic
- Same secret references
- Outputs wired correctly

### 7. Explain the new workflow

Make sure the user understands:
- `recipe.yml` is now the source of truth — edit the recipe, not the compiled workflow
- Run `reci compile recipe.yml` after changes to regenerate the workflow
- `reci validate` catches wiring problems before they hit CI
- Config lives in `pyproject.toml` (or their chosen config source)

## Edge cases

- **Multiple workflow files**: Migrate one at a time. Each gets its own recipe.
- **Reusable workflows** (`workflow_call`): reci doesn't support these yet — note this and leave them as-is.
- **Composite actions**: reci handles these the same as regular actions.
- **Self-hosted runners**: `runs-on` passes through unchanged.
- **Partial migration**: It's fine to migrate only some jobs. The recipe can coexist with hand-written workflow sections (though the user will need to manage those manually).
