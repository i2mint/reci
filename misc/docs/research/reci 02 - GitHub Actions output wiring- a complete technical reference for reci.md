# GitHub Actions output wiring: a complete technical reference for reci

GitHub Actions outputs are string-only, step-scoped values that must be explicitly forwarded through up to three layers—step → job → workflow—to reach downstream consumers. **Building an auto-wiring tool like reci requires navigating non-obvious edge cases**: non-deterministic matrix outputs, silent empty-string fallbacks for unset values, string-to-boolean coercion traps, and secret-masking that silently drops outputs. This report catalogs every mechanism, limit, and gotcha relevant to automatic output wiring, drawn from official documentation, runner source code, and community-reported issues.

The core insight is that GitHub Actions' output system was designed for explicit, manual wiring. Automating that wiring demands a precise model of scoping rules, context availability at each YAML key, and the matrix job aggregation gap that remains unresolved after four years of community requests [1].

---

## How steps produce and consume outputs

GitHub Actions offers three action types—composite, JavaScript/Docker, and inline `run:`—each with a distinct mechanism for setting outputs, all converging on the same `$GITHUB_OUTPUT` environment file.

**Composite actions** declare outputs in `action.yml` with a mandatory `value:` field that maps to an internal step's output [2]:

```yaml
# action.yml (composite)
outputs:
  random-number:
    description: "Random number"
    value: ${{ steps.generator.outputs.random-number }}
runs:
  using: "composite"
  steps:
    - id: generator
      run: echo "random-number=$(echo $RANDOM)" >> $GITHUB_OUTPUT
      shell: bash
```

The `value:` field is **required and unique to composite actions**—it is the explicit wiring from an internal step to the action's public interface. Composite actions do not receive `INPUT_*` environment variables automatically; inputs must be accessed via `${{ inputs.name }}` or passed explicitly through `env:` [2].

**JavaScript actions** use `@actions/core.setOutput()`, which since v1.10.0 writes to `$GITHUB_OUTPUT` internally rather than emitting the deprecated `::set-output` stdout command [3]. Docker actions write to the same file from their entrypoint script—the runner mounts the file into the container:

```python
# Python inside a Docker action
import os
with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
    f.write("result=some-value\n")
```

Unlike composite actions, JavaScript and Docker actions declare outputs in `action.yml` **without** a `value:` field—the action code itself is responsible for writing the output. Importantly, **undeclared outputs are still accessible**: a JS/Docker action can write any key to `$GITHUB_OUTPUT` and consumers can reference it, even if it is absent from `action.yml` [2]. Composite actions, however, require explicit declaration.

**Inline `run:` steps** write directly to `$GITHUB_OUTPUT`. Multiline values use a heredoc delimiter syntax:

```yaml
- id: multi
  run: |
    {
      echo 'JSON_RESPONSE<<EOF'
      curl -s https://api.example.com/data
      echo EOF
    } >> "$GITHUB_OUTPUT"
```

A critical gotcha: **always use `>>` (append), never `>` (overwrite)**. Using `>` truncates the file and destroys all previously set outputs for that step [4]. The delimiter string (`EOF` above) must not appear on its own line within the value content—GitHub recommends generating a random delimiter at runtime to prevent injection attacks [4].

---

## Naming rules, case sensitivity, and the empty-string default

Output names follow identifier rules: they must start with a letter or underscore, and contain only alphanumeric characters, hyphens, or underscores [2]. Outputs are consumed via `${{ steps.<id>.outputs.<name> }}`.

**Case sensitivity is nuanced.** Context property accesses in GitHub Actions expressions are **case-insensitive** [5]—`steps.build.outputs.Version` and `steps.build.outputs.version` resolve identically. Input IDs declared in `action.yml` are explicitly **converted to lowercase at runtime** [2]. For reci, this means name matching should normalize to lowercase.

When a referenced output was never set, the expression evaluates to an **empty string**—not `null`, and no error is raised [6]. This applies equally to three scenarios: the step was skipped (its `if:` was false), the step ran but didn't write the output, or the output was explicitly set to empty. **There is no way to distinguish between these cases** [7]. In boolean contexts, an empty string is falsy, so `if: ${{ steps.x.outputs.flag }}` will not execute when the output is unset.

**Maximum output sizes** are **1 MB per job** (all outputs from all steps combined) and **50 MB per workflow run**, measured in approximate UTF-16 encoding [8]. Exceeding the per-job limit causes the job to fail when the runner evaluates job outputs at completion. For data exceeding these limits, artifacts (up to 5 GB each) are the standard alternative [9].

---

## Crossing job boundaries requires explicit forwarding

Step outputs are scoped to their job. Crossing a job boundary requires a three-layer chain: step output → job output declaration → `needs` consumption. There is no shortcut.

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    outputs:
      version: ${{ steps.meta.outputs.version }}  # Layer 2
    steps:
      - id: meta
        run: echo "version=1.2.3" >> $GITHUB_OUTPUT  # Layer 1

  deploy:
    needs: build  # Dependency declaration
    runs-on: ubuntu-latest
    steps:
      - run: echo "${{ needs.build.outputs.version }}"  # Layer 3
```

The downstream job **must** declare `needs:` to access outputs—without it, the `needs` context is empty and the jobs may run in parallel [10]. Job output expressions are evaluated on the runner **at the end of each job** [8]. Referencing a non-existent job output returns an empty string, silently [6].

**Reusable workflows add a fourth layer.** A called workflow's outputs must be declared under `on.workflow_call.outputs`, and each value must reference a **job-level** output using `${{ jobs.<job_id>.outputs.<name> }}`—not step outputs directly [11]:

```yaml
# Called workflow
on:
  workflow_call:
    outputs:
      image-tag:
        value: ${{ jobs.build.outputs.tag }}  # jobs context, not steps

# Caller workflow
jobs:
  deploy-workflow:
    uses: ./.github/workflows/build.yml
  notify:
    needs: deploy-workflow
    steps:
      - run: echo "${{ needs.deploy-workflow.outputs.image-tag }}"
```

A known bug affects `${{ jobs.<id>.result }}` when used as a reusable workflow output—it often resolves to an empty string for skipped or failed jobs. The workaround is adding a dummy output with `${{ toJSON(jobs) }}` to force proper evaluation [12].

---

## Matrix outputs are non-deterministic by design

This is the single most dangerous edge case for auto-wiring. When a matrix job produces outputs, **all matrix instances write to the same output namespace**. If multiple instances set the same key, **the last instance to finish wins**, and execution order is non-deterministic [13]. Empty outputs are discarded during the merge, so if only one instance sets a given key, it is retained reliably.

```yaml
jobs:
  build:
    strategy:
      matrix:
        platform: [linux, windows, macos]
    outputs:
      version: ${{ steps.v.outputs.version }}  # ⚠️ Non-deterministic!
    steps:
      - id: v
        run: echo "version=${{ matrix.platform }}-1.0" >> $GITHUB_OUTPUT
```

The downstream job receives one value—potentially from any matrix leg. One user reported this led to deploying the wrong Helm chart to a Kubernetes cluster [1]. The documented workaround uses **unique output names per matrix instance**, exploiting the empty-output discard behavior:

```yaml
jobs:
  build:
    strategy:
      matrix:
        version: [1, 2, 3]
    outputs:
      output_1: ${{ steps.gen.outputs.output_1 }}
      output_2: ${{ steps.gen.outputs.output_2 }}
      output_3: ${{ steps.gen.outputs.output_3 }}
    steps:
      - id: gen
        run: echo "output_${{ matrix.version }}=${{ matrix.version }}" >> $GITHUB_OUTPUT
```

This pattern requires static, pre-known matrix values and repetitive YAML. A runner PR to support `matrix` context in output keys was merged in March 2023, but **the server-side changes were never completed** [1]. For dynamic matrices, the artifact-based pattern using `actions/upload-artifact@v4` with unique names per matrix leg and `actions/download-artifact@v4` with `merge-multiple: true` is the most reliable aggregation method [14]. Third-party actions like `cloudposse/github-action-matrix-outputs-write` provide a convenience wrapper around this approach [15].

---

## Patterns: environment files, state, and when to use each

**`$GITHUB_ENV` vs `$GITHUB_OUTPUT`** represents a scoping tradeoff. Environment variables set via `$GITHUB_ENV` are available to **all subsequent steps** in the job as shell environment variables (`$MY_VAR`) and expression variables (`${{ env.MY_VAR }}`). Outputs are scoped to the producing step and require explicit reference by step ID [16]. Key differences:

- `$GITHUB_ENV` variables **cannot cross job boundaries**; outputs can be promoted to job outputs
- `$GITHUB_ENV` doesn't require a step `id:`; outputs do
- `$GITHUB_ENV` is a **larger attack surface**—a compromised step can overwrite `PATH` or other critical variables affecting all subsequent steps [16]
- Outputs provide cleaner data provenance for complex workflows

Use `$GITHUB_ENV` for values consumed by many subsequent steps (e.g., a version string used everywhere). Use `$GITHUB_OUTPUT` for values that need to cross job boundaries, feed into conditionals, or maintain explicit data lineage.

**`$GITHUB_STATE`** enables communication between an action's `pre:`, `main:`, and `post:` execution phases. Writing `echo "key=value" >> $GITHUB_STATE` makes the value available as `STATE_key` in subsequent phases [4]. This is scoped to the specific action instance—no other action in the job can access it. The `@actions/core` package exposes this via `saveState()` and `getState()` [3]. Composite actions **do not support** `pre:` and `post:` phases [17].

**Secret masking silently drops outputs.** If the runner detects that an output value matches or partially matches a masked secret, the output is **silently dropped** with a warning: `"Skip output {key} since it may contain secret."` [18]. This affects not just secrets but also values that happen to contain substrings matching secrets—AWS account IDs, short tokens, and even Docker digests have been reported as false positives [18]. The workaround is to encrypt the value before setting it as an output and decrypt it in the consuming job.

---

## What reci must handle to auto-wire safely

Automatic name-matching between outputs and inputs introduces several categories of risk that reci must address systematically.

**Name collisions** occur when multiple steps produce the same output name. Within a job this is safe—outputs are namespaced by step ID—but reci must choose which step's output to wire when a downstream step's input name matches multiple upstream outputs. Strategies include nearest-predecessor priority, requiring explicit disambiguation, or emitting a warning. At the job output level, names must be unique, so reci should suggest prefixed names (e.g., `npm_version`, `git_version`) when promoting ambiguous step outputs [10].

**Type coercion is a minefield.** All outputs are strings, but reusable workflow inputs can declare `type: boolean` or `type: number` [19]. Passing the string `"false"` to a boolean input throws `Unexpected type of value 'false', expected type: Boolean` [20]. Worse, using a string output directly in an `if:` expression treats any non-empty string—including `"false"`—as truthy. reci should inject `== 'true'` comparisons when wiring string outputs to boolean-typed inputs, and `fromJSON()` wrapping for complex types.

**Context availability constrains injection points.** The `steps` context is available in `steps.with`, `steps.run`, `steps.if`, `steps.env`, and `jobs.<id>.outputs`—but **not** in `jobs.<id>.if`, `jobs.<id>.runs-on`, `jobs.<id>.strategy`, or `jobs.<id>.with` (reusable workflow calls) [21]. The `needs` context is available at most job-level keys. reci must embed the full context availability table and validate that injected expressions only use contexts legal at the injection point. Notably, `steps.uses` does not accept any expressions—action references must be static strings [22].

**Dynamic output names defeat static analysis.** Steps can write arbitrary keys to `$GITHUB_OUTPUT` at runtime using shell variable interpolation, but these names cannot be predicted from YAML alone. reci should parse `run:` blocks for `echo "name=value" >> $GITHUB_OUTPUT` patterns as a heuristic, but must skip wiring and warn when variable interpolation appears in the output name. Encouraging a single JSON-valued output rather than multiple dynamic keys provides a more analyzable interface [23].

**`action.yml` metadata is incomplete by design.** The `required` field on inputs is **not enforced at runtime**—an action with `required: true` will still execute with a missing input [24]. reci should validate required inputs on behalf of GitHub Actions. Default values in `action.yml` mean reci should only wire an input when a matching upstream output exists—if no match is found and a default exists, leaving it unwired is correct. Input IDs are lowercased at runtime, so matching should be case-insensitive. Consider normalizing hyphens and underscores (`kebab-case` ↔ `snake_case`) as a fuzzy-match option with user confirmation [2].

---

## Conclusion

GitHub Actions' output system is deceptively simple on the surface—`echo "key=value" >> $GITHUB_OUTPUT`—but the layers of scoping, forwarding, and evaluation create a complex wiring problem. For reci, the highest-risk areas are **matrix output non-determinism** (which should trigger a hard warning or block), **string-to-boolean coercion** (which requires expression injection), and **cross-job boundary translation** (which demands automatic generation of `jobs.*.outputs` mappings and `needs:` declarations). The context availability table is the authoritative constraint on where expressions can be injected, and reci should embed it as a validation layer. The output size limit of **1 MB per job** means reci should also detect when workflows approach this boundary and suggest artifacts as an alternative. Finally, the secret-masking system's tendency to silently drop outputs means reci should warn users when wiring values that could trigger false-positive masking.

## References

[1] GitHub Community Discussion #17245, "Jobs need a way to reference all outputs of matrix jobs." https://github.com/orgs/community/discussions/17245

[2] GitHub Docs, "Metadata syntax for GitHub Actions." https://docs.github.com/en/actions/creating-actions/metadata-syntax-for-github-actions

[3] GitHub Actions Toolkit, "@actions/core README." https://github.com/actions/toolkit/blob/main/packages/core/README.md

[4] GitHub Docs, "Workflow commands for GitHub Actions." https://docs.github.com/en/actions/using-workflows/workflow-commands-for-github-actions

[5] yossarian.net, "TIL: GitHub Actions is surprisingly case-insensitive." https://yossarian.net/til/post/github-actions-is-surprisingly-case-insensitive/

[6] GitHub Docs, "Contexts — accessing contextual information about workflow runs." https://docs.github.com/en/actions/learn-github-actions/contexts

[7] GitHub Actions Runner Issue #924, "Cannot distinguish between unset and empty output." https://github.com/actions/runner/issues/924

[8] GitHub Docs, "Workflow syntax for GitHub Actions." https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions

[9] GitHub Docs, "Usage limits, billing, and administration." https://docs.github.com/en/actions/learn-github-actions/usage-limits-billing-and-administration

[10] GitHub Docs, "Defining outputs for jobs." https://docs.github.com/en/actions/using-jobs/defining-outputs-for-jobs

[11] GitHub Docs, "Reusing workflows." https://docs.github.com/en/actions/using-workflows/reusing-workflows

[12] GitHub Actions Runner Issue #2495, "Reusable workflow output with jobs.<id>.result resolves empty." https://github.com/actions/runner/issues/2495

[13] GitHub Community Discussion #42010, "Matrix job outputs — last to finish wins." https://github.com/orgs/community/discussions/42010

[14] GitHub Actions, "actions/download-artifact v4 — merge-multiple option." https://github.com/actions/download-artifact

[15] Cloud Posse, "github-action-matrix-outputs-write." https://github.com/cloudposse/github-action-matrix-outputs-write

[16] GitHub Community Discussion #55294, "GITHUB_ENV vs GITHUB_OUTPUT." https://github.com/orgs/community/discussions/55294

[17] GitHub Actions Runner Issue #1478, "Composite action pre/post support." https://github.com/actions/runner/issues/1478

[18] GitHub Community Discussion #37942, "Job output is empty — secret masking false positives." https://github.com/orgs/community/discussions/37942

[19] GitHub Blog Changelog, "GitHub Actions: Inputs unified across manual and reusable workflows." https://github.blog/changelog/2022-06-10-github-actions-inputs-unified-across-manual-and-reusable-workflows/

[20] GitHub Actions Runner Issue #1483, "Boolean inputs from outputs cause type errors." https://github.com/actions/runner/issues/1483

[21] GitHub Docs, "Contexts — context availability." https://docs.github.com/en/actions/learn-github-actions/contexts#context-availability

[22] GitHub Actions Runner Issue #895, "Cannot use expressions in uses field." https://github.com/actions/runner/issues/895

[23] GitHub Community Discussion #10529, "Dynamic output names in composite actions." https://github.com/orgs/community/discussions/10529

[24] GitHub Actions Runner Issue #1070, "Required inputs are not validated at runtime." https://github.com/actions/runner/issues/1070