# How five CI systems model pipelines as DAGs

**Every modern CI system is secretly a DAG compiler — but they differ radically in how they expose that graph to users.** Dagger constructs the DAG implicitly through typed method chains in Python or Go. Tekton and Argo Workflows declare it in YAML with explicit dependency fields. Concourse derives it from resource-flow constraints. GitHub Actions splits it across two tiers: a job-level DAG via `needs:` and sequential steps within each job. For a tool like `reci` that compiles declarative recipes into GitHub Actions YAML, the most instructive patterns come from Dagger's typed artifact passing, Tekton's dual-mechanism dependency model, and Hamilton's function-signature-driven DAG inference — while the biggest pitfalls to avoid are GitHub Actions' untyped string-only outputs and Argo's error-prone string-interpolated variable references.

This report examines each system across six dimensions — DAG representation, data flow, parameterization, conditional execution, validation, and the "impure step" problem — then distills concrete recommendations for building `reci`.

---

## DAG representation spans a spectrum from pure code to implicit derivation

The five systems occupy distinct positions on the declarative-vs-programmatic spectrum. **Dagger** sits at the fully programmatic end: pipelines are Python (or Go, TypeScript) code where each SDK method call (`.from_()`, `.with_exec()`, `.with_directory()`) appends a node to the DAG [1]. The engine receives GraphQL queries derived from these chains and "computes a Directed Acyclic Graph of low-level operations required to compute the result" [2]. Edges are implicit — the output of one call is the input to the next via immutable builder patterns, making cycles structurally impossible.

**Tekton** and **Argo Workflows** both use declarative YAML but express edges differently. Tekton's Pipeline YAML defines tasks as nodes, with edges created two ways: `runAfter` for pure ordering, and `$(tasks.taskA.results.someResult)` references that **automatically create data-dependency edges** [3]. Argo's `dag` template type uses an explicit `dependencies: [A, B]` list on each task, plus a more expressive `depends` field supporting status conditions like `A.Succeeded || A.Failed` [4]. Argo also offers a `steps` template as an alternative — a nested list where outer lists run sequentially and inner lists run in parallel — which many users find more intuitive for linear workflows [5].

**Concourse CI** takes the most unusual approach: its DAG is **implicitly derived** from resource usage. There is no `depends_on` field. Instead, when Job B declares `get: my-resource, passed: [job-A]`, it means "only use versions of this resource that successfully passed through Job A" — and this `passed:` constraint creates the DAG edge [6]. The pipeline visualization auto-generates from these resource relationships, providing immediate structural feedback.

**GitHub Actions** uses the simplest explicit model: `needs: [job-a, job-b]` on a job creates edges in a job-level DAG [7]. Jobs without `needs:` run in parallel by default. Within a job, steps are always sequential with no intra-job parallelism. This two-tier model — DAG of jobs, sequence of steps — is what `reci` must compile to.

| System | DAG definition | Nodes | Edges | Parallelism |
|---|---|---|---|---|
| Dagger | Programmatic (SDK code) | API method calls | Implicit from method chaining | Engine-managed, automatic |
| Tekton | Declarative YAML (CRDs) | PipelineTasks | `runAfter` + result references | Tasks without deps run in parallel |
| Argo Workflows | Declarative YAML | DAG tasks | `dependencies` / `depends` fields | Tasks with satisfied deps run immediately |
| Concourse | Implicit from resources | Jobs | `passed:` constraints on `get` steps | Jobs with no resource constraints run in parallel |
| GitHub Actions | Declarative YAML | Jobs | `needs:` field | Jobs without `needs:` run in parallel |

---

## Data flow mechanisms reveal a universal tension between typed contracts and filesystem sharing

Every system grapples with the same fundamental question: how does output from Task A reach Task B? The answers cluster around three patterns.

**Typed artifact passing** is Dagger's approach. Data flows via first-class typed objects — `Container`, `Directory`, `File`, `Secret` — that are content-addressed and managed by the engine [8]. A function returning `dagger.File` explicitly wires its output to a consumer expecting that type. This enables automatic caching: identical inputs produce cache hits, changed inputs recompute only the affected subgraph. The type system prevents passing a `str` where a `Directory` is expected, catching errors before execution.

**Small-data parameters vs. large-data artifacts** is the pattern shared by Tekton and Argo. Tekton's Results are strings written to `/tekton/results/<name>`, limited to **4,096 bytes total per Task** due to Kubernetes termination message constraints [3]. Cross-task references use `$(tasks.clone.results.commit-sha)` syntax. For large data, Tekton Workspaces provide shared PVC-backed volumes — but critically, **workspaces do not create implicit DAG edges**, a notorious footgun requiring manual `runAfter` [9]. Argo makes the same distinction: parameters are small strings stored in the workflow CRD status; artifacts are files stored in S3/GCS, referenced with `from: "{{tasks.step-A.outputs.artifacts.output-artifact-1}}"` [4].

**GitHub Actions' cross-job output mechanism** requires a three-step ceremony: (1) write `key=value` to `$GITHUB_OUTPUT` in a step, (2) map step outputs to job-level `outputs:` in the job definition, (3) reference via `needs.<job>.outputs.<name>` in the consuming job [7]. All outputs are **string-only** with a 1 MB per-output limit and 50 MB total per workflow run. Passing structured data requires JSON serialization and `fromJSON()` deserialization. For binary/large data, `actions/upload-artifact` and `actions/download-artifact` provide an artifact-transfer mechanism, but it is convention-based — not wired into the DAG model.

**Concourse's resource model** is the most distinctive. Between jobs, data *must* flow through external resources (S3, git, Docker registries) via `put` and `get` steps [6]. Within a job, tasks pass artifacts as named directories mounted into subsequent containers, with `input_mapping` and `output_mapping` for renaming. The `passed:` constraint ensures version consistency: the exact same resource version flows through the entire pipeline chain. This is elegant but heavyweight — passing a build artifact to the next job requires an external storage round-trip.

---

## Parameterization ranges from global injection to per-function scoping

**Dagger** scopes parameters entirely per-function. Each Dagger Function declares typed parameters in its signature (`def build(self, src: dagger.Directory, arch: str)`) and parameters are injected at the call site via CLI args, environment variables, or `.env` files [1]. Secrets are a first-class type (`dagger.Secret`) with dedicated providers (Vault, AWS Secrets Manager, environment variables) and automatic redaction — they are **never logged, cached, or written to container filesystems** [10].

**Tekton** uses a two-level scoping model. Pipeline-level params are declared in the Pipeline spec and supplied at PipelineRun time. These are forwarded to individual Task params via explicit mapping in the `tasks[].params[]` field. Task params are scoped to the Task and accessible in Steps via `$(params.name)` [3]. Parameter types (`string`, `array`, `object`) are validated at admission time.

**Argo Workflows** provides both global and template-level parameters. Workflow-level `arguments.parameters` are accessible everywhere as `{{workflow.parameters.X}}` without needing to declare inputs. Template-level `inputs.parameters` must be explicitly passed via `arguments` from the calling task [4]. Parameters can also be sourced from ConfigMaps and Secrets.

**Concourse** uses `((var))` interpolation syntax with static vars supplied via `fly set-pipeline --var` and dynamic vars resolved at runtime from credential managers (Vault, CredHub, AWS SSM) [6]. A notable feature: vars are fetched **as late as possible** before step execution, enabling short-lived credentials. The `load_var` step can capture runtime values from files into the build-local variable namespace.

**GitHub Actions** offers the most fragmented parameter space: `workflow_dispatch` inputs (manual triggers), `workflow_call` inputs (reusable workflows), `env` context at three scopes (workflow/job/step), `secrets` context, and `vars` context for non-secret configuration [7]. There is **no native mechanism** to inject values from `pyproject.toml` — a step must explicitly read the file and write parsed values to `$GITHUB_OUTPUT`. This is precisely the gap `reci` should fill by reading project config at compile time and baking values into the generated YAML.

---

## Conditional execution is first-class in code-based systems but bolted-on in YAML

**Dagger** handles conditionals with native host-language `if/else`, since pipelines are just Python code [1]. A subtlety: because the DAG is lazily evaluated, conditionals that depend on runtime results (e.g., container output) require `await`ing the result first, which forces evaluation of the upstream chain.

**Tekton's `when` expressions** guard Task execution with `input`/`operator`/`values` triples supporting `in` and `notin` operators [3]. They can reference Pipeline params, Task results, and workspace bindings. When a guarded task is skipped, ordering-dependent tasks (`runAfter`) still execute by default — only tasks consuming missing results are skipped. This behavior was historically controversial and changed across versions (TEP-0059), creating a confusing landscape for users.

**Argo's `when` field** uses govaluate expression syntax and supports `&&`, `||`, parentheses, and comparison operators [4]. Expressions can reference prior task results: `when: "{{steps.flip-coin.outputs.result}} == heads"`. Skipped tasks don't cascade — only the specific guarded task is affected.

**Concourse** has the weakest conditional support among the five systems. There is no `if:` or `when:` step. Users work around this with `try` (swallows failures), `on_success`/`on_failure` hooks, and `ensure` (always-runs, like `finally`) [6]. An open RFC (#66) exists for a proper conditional step, but it remains unimplemented. This is widely cited as a significant pain point.

**GitHub Actions** provides `if:` expressions on both jobs and steps, with status functions (`success()`, `failure()`, `always()`, `cancelled()`) and access to outputs via expression syntax [7]. A critical pitfall: **when a job is `if:`-skipped, downstream jobs are also skipped by default** — the "skipped upstream" status propagates through the DAG. This means `if:` doesn't just skip one node; it can silently cascade through the graph.

---

## Validation depth varies enormously, from zero to full type systems

**Dagger** provides the deepest validation through its layered type system [1]. Host-language type checkers (mypy, pyright) catch type mismatches at development time. The underlying GraphQL schema validates field existence, argument types, and required parameters. The CLI validates argument types at invocation. Cycle detection is unnecessary because the immutable builder pattern makes cycles structurally impossible.

**Tekton's Kubernetes admission webhook** runs Kahn's algorithm for cycle detection (rewritten for performance after timing out on large pipelines, Issue #5420), validates parameter names and types, checks `runAfter` references against existing tasks, and validates result reference syntax [3]. It **cannot** validate whether a referenced Task actually exists in the cluster or whether a Task will produce the results it declares — those are runtime errors.

**Argo's `argo lint`** checks YAML schema compliance, template references, parameter resolution, and expression syntax [4]. However, **Argo lacks a built-in Validating Admission Webhook** (Issue #13503), meaning invalid workflows submitted directly via `kubectl apply` bypass validation entirely. Users must rely on external policy engines like OPA Gatekeeper.

**Concourse's `fly validate-pipeline`** performs local structural validation — YAML syntax, schema compliance, required fields [6]. The `--check-creds` flag validates that all `((var))` references resolve. But it **cannot validate task configs loaded from files at runtime** — a fundamental limitation of its late-binding architecture.

**GitHub Actions** validates workflow YAML at push time for YAML syntax, schema compliance, and cycle detection in `needs:` [7]. It does **not** validate whether referenced actions exist, whether expression references resolve, or whether output types are correct. The third-party tool **`actionlint`** (3.7k GitHub stars) provides dramatically deeper analysis: strong expression type checking, action input/output validation, shellcheck integration for `run:` scripts, security checks, and context availability validation [11]. For `reci`, integrating `actionlint`-level validation at compile time would be a major value-add.

---

## The impure step problem is universal and unsolved

Every system eventually delegates to opaque container commands, breaking whatever typed contract exists at the DAG level.

**Dagger's `Container.with_exec()`** accepts `list[str]` command arguments and modifies the container filesystem opaquely [1]. The chain `from_() → with_directory() → with_exec() → file()` has a typed envelope (`Container → Container → File`) but the `with_exec` node is a black box. Dagger mitigates this by encouraging users to wrap shell commands in typed Dagger Functions with declared inputs/outputs.

**Tekton Steps** are container specs with arbitrary `command`/`args` or `script` fields [3]. A Task might declare `results: [{name: digest}]` but nothing enforces that the step actually writes to `$(results.digest.path)`. Failure surfaces only at runtime. The newer **StepActions** (v1alpha1) add reusable, parameterized step definitions — moving toward structured building blocks but still fundamentally trust-based.

**Argo** relies on containers writing output parameters to specific file paths (`valueFrom.path: /tmp/output.txt`), and missing files have historically **crashed the workflow controller itself** (Issue #5912) [4]. Artifacts can be marked optional as a mitigation, but there's no compile-time verification that containers produce their declared outputs.

**Concourse** tasks are "described as pure functions of code in the docs, but in practice they can have side effects" [6]. The resource abstraction (check/in/out) adds versioned typing at the inter-job boundary, but within a job, task scripts are untyped black boxes operating on named directories with no content schema.

**GitHub Actions** has the starkest split: `run:` steps are entirely opaque shell commands with no declared inputs or outputs [7]. Action steps (`uses:`) have an `action.yml` contract with named inputs and outputs — but **action inputs have no `type:` property** and are always strings. Only `workflow_call` inputs support `type: string | number | boolean`. Composite actions provide a partial solution by bundling steps under a typed interface, but the internal `run:` steps remain untyped. **This is the core problem `reci` should solve**: by defining recipe nodes as GitHub Actions with typed `action.yml` contracts, the compiler can validate the data-flow graph at compile time, catching output name typos, type mismatches, and missing wiring before any YAML is generated.

---

## What `reci` should borrow, avoid, and build on

**Borrow from Dagger**: typed artifact passing where intermediate values (`Directory`, `File`, `Secret`) are first-class typed objects; the immutable builder pattern that makes cycles structurally impossible; content-addressed caching keyed by inputs; secrets as a distinct type preventing accidental exposure [1][2].

**Borrow from Tekton**: the dual-mechanism dependency model (pure ordering vs. data-dependency edges inferred from result references); definition-time DAG validation with cycle detection; the `finally` task concept as a separate execution phase [3].

**Borrow from Argo**: the separation of template definition from invocation (define a reusable template once, reference it with different arguments); the enhanced `depends` field with status conditions (`.Succeeded`, `.Failed`) enabling sophisticated error-handling branches [4].

**Borrow from Concourse**: implicit DAG derivation from data flow declarations rather than explicit `depends_on`; version-consistent resource tracking through pipeline stages; offline validation via `fly validate-pipeline` [6].

**Borrow from GitHub Actions**: the two-tier model (jobs as DAG, steps as sequence) which is the compilation target; matrix strategies for cross-platform testing; the `workflow_dispatch` input pattern for parameterization [7].

**Avoid from Dagger**: confusing lazy-vs-eager semantics that have been a documented source of user confusion (Issue #4668); the invisible DAG that exists only inside the engine with no user-facing inspection [1].

**Avoid from Tekton**: workspaces that don't create implicit edges (a notorious footgun); the 4 KB result size limit; YAML verbosity requiring 50+ lines for simple pipelines [3].

**Avoid from Argo**: string-interpolated template variables (`{{tasks.X.outputs.parameters.Y}}`) that are invisible to linters and not type-checked; the dual `dependencies`/`depends` fields that confuse users; the missing admission webhook [4].

**Avoid from Concourse**: no native conditional execution; requiring external storage round-trips for inter-job artifact passing; opaque task scripts with no type information [6].

**Avoid from GitHub Actions**: the three-step output wiring ceremony (write `$GITHUB_OUTPUT`, map to job `outputs:`, reference via `needs:`); string-only untyped outputs; the `if:`-skip cascade that propagates through the DAG; no data dependency tracking in the structural model [7].

---

## Python libraries that enable DAG compilation for CI

No existing Python library directly compiles a typed DAG of tasks into GitHub Actions YAML — this is genuinely a gap in the ecosystem. But strong building blocks exist.

**`graphlib.TopologicalSorter`** from Python's standard library (3.9+) provides cycle detection via `CycleError` and parallel-ready scheduling via `get_ready()`/`done()`, making it an ideal zero-dependency foundation for DAG validation [12]. **NetworkX** offers richer algorithms (`is_directed_acyclic_graph()`, `find_cycle()`, `topological_sort()`, `ancestors()`) and visualization capabilities for more complex graph analysis [13].

**Apache Hamilton** (formerly DAGWorks-Inc/hamilton, ~2k stars) is the most architecturally relevant model. It builds DAGs automatically from Python function signatures — function name becomes the output node, parameter names become input dependencies — using type annotations to validate type compatibility between connected nodes [14]. The separation of DAG "definition" (modules) from "execution" (Driver) mirrors the "compile DAG" vs. "emit YAML" pattern that `reci` needs.

**pipefunc** (~458 stars) provides a lightweight decorator-based pipeline system built on NetworkX, where `@pipefunc` specifies output names and `Pipeline` auto-builds the DAG [15]. Its pattern of decorating functions with output names, building a pipeline, then executing/visualizing is very close to what a CI recipe compiler requires.

For the YAML generation side, **Pydantic combined with `pydantic-yaml`** enables defining GitHub Actions workflow structures as typed Python models and serializing them to YAML [16]. The `datamodel-code-generator` tool can auto-generate Pydantic models from the official GitHub Actions JSON Schema at `json.schemastore.org/github-workflow.json`, providing a fully typed workflow model [17]. Post-generation validation can use `jsonschema` against the same schema, or shell out to `actionlint` for deep semantic checking [11].

The recommended architecture for `reci` combines these: Hamilton-style function-signature DAG inference for recipe definition → `graphlib.TopologicalSorter` for validation and ordering → Pydantic models for the GitHub Actions workflow structure → YAML serialization → `actionlint` validation of the output.

---

## Conclusion

The five CI systems converge on a shared insight — that pipelines are fundamentally DAGs of typed data transformations — but diverge sharply in how much of that insight they expose to users. Dagger proves that a full type system over pipeline artifacts dramatically improves correctness and caching. Tekton and Argo demonstrate that even within YAML, distinguishing data dependencies from ordering dependencies enables better graph inference and validation. Concourse shows that deriving the DAG from data flow declarations is more intuitive than explicit dependency lists. And GitHub Actions reveals the limitations of the compilation target: untyped string outputs, no structural data-dependency tracking, and a verbose three-step wiring ceremony.

For `reci`, the highest-leverage opportunity is **closing the type gap** that exists in GitHub Actions. By modeling each recipe node as a GitHub Action with typed inputs and outputs (matching `action.yml` contracts), inferring `needs:` edges from data-flow declarations, auto-generating the output wiring boilerplate, and validating the entire graph at compile time — including cycle detection, missing-output detection, and type compatibility checks — `reci` can provide the developer experience of Dagger's typed pipelines while targeting GitHub Actions' universal execution platform. The building blocks exist in Python's ecosystem (Hamilton for DAG inference, graphlib for validation, Pydantic for typed YAML generation) but have never been assembled for this purpose.

---

## References

[1] Dagger Documentation, "Programmable Pipelines," https://docs.dagger.io/features/programmable-pipelines/

[2] Dagger Documentation, "Architecture," https://docs.dagger.io/manuals/developer/architecture/

[3] Tekton Documentation, "Pipelines," https://tekton.dev/docs/pipelines/pipelines/

[4] Argo Workflows Documentation, "DAG Template," https://argo-workflows.readthedocs.io/en/latest/walk-through/dag/

[5] Argo Workflows GitHub, "DAG proposal discussion," https://github.com/argoproj/argo-workflows/issues/625

[6] Concourse CI Documentation, "Pipeline Mechanics," https://concourse-ci.org/pipelines.html

[7] GitHub Documentation, "Workflow syntax for GitHub Actions," https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions

[8] Dagger Documentation, "Core Types," https://docs.dagger.io/getting-started/types/

[9] Tekton Documentation, "Workspaces," https://tekton.dev/docs/pipelines/workspaces/

[10] Dagger Documentation, "Secrets Integration," https://docs.dagger.io/features/secrets/

[11] rhysd, "actionlint — Static checker for GitHub Actions workflow files," https://github.com/rhysd/actionlint

[12] Python Documentation, "graphlib — Functionality to operate with graph-like structures," https://docs.python.org/3/library/graphlib.html

[13] NetworkX Documentation, "Directed Acyclic Graphs," https://networkx.org/documentation/stable/reference/algorithms/dag.html

[14] Apache Hamilton, "Hamilton: A scalable general purpose micro-framework for defining dataflows," https://github.com/apache/hamilton

[15] pipefunc, "A Python library for defining and running function pipelines," https://github.com/pipefunc/pipefunc

[16] NowanIlfideme, "pydantic-yaml — YAML serialization for Pydantic models," https://github.com/NowanIlfideme/pydantic-yaml

[17] koxudaxi, "datamodel-code-generator — Generate Pydantic models from JSON Schema," https://github.com/koxudaxi/datamodel-code-generator