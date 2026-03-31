# CI Recipe Validation: Tools, Patterns, and UX Design

*Author: Thor Whalen*
*Date: March 28, 2026*

---

A CI recipe validator that checks data flow correctness, DAG structure, purity, and config completeness can draw heavily from existing tools rather than building from scratch. **actionlint** already solves expression type-checking and cycle detection for GitHub Actions; **JSON Schema** handles structural validation; and the **ESLint off/warn/error severity model** provides the best-proven pattern for configurable multi-level diagnostics. The gap — and thus the opportunity — lies in stitching these layers together under a unified Python-native validation framework that adds domain-specific semantic checks (data flow sourcing, purity contracts) on top of what existing tools provide.

This report surveys the landscape across three dimensions: what existing CI validation tools do and how they work internally, which Python libraries and linter architectures offer reusable patterns, and how validation results should be presented to maximize developer productivity.

---

## 1. actionlint sets a high bar for workflow validation

actionlint [1], a Go-based static checker by rhysd with **~3,700 GitHub stars**, is the most thorough open-source GitHub Actions linter. It performs **14 categories of checks** including syntax validation, `${{ }}` expression type-checking, action input/output verification, shell script linting (via shellcheck integration), runner label validation, `needs:` **cycle detection**, glob pattern validation, and deprecated-command detection.

The tool's expression engine deserves special attention for anyone building a data-flow validator. actionlint implements a **full type system for GitHub Actions expressions** with seven types: `Any`, `String`, `Number`, `Bool`, `Null`, `Object` (strict or loose), and `Array`. Context objects like `github`, `matrix`, `steps`, and `needs` are modeled as strictly-typed objects whose properties are validated at each point in the workflow. The `steps` context is built incrementally — each step's outputs become typed based on action metadata, so downstream `${{ steps.build.outputs.version }}` references are checked against what the action actually declares [1].

For action schema discovery, actionlint embeds a **pre-compiled dataset of 100+ popular actions** (generated at build time, stored in `popular_actions.go`), resolves local actions by reading `action.yml` from the filesystem, and resolves local reusable workflows by parsing their YAML. Critically, **it never makes network requests** — actions outside the popular dataset and not local simply receive `AnyType`, silently skipping input/output validation rather than producing false positives. Only major-version tags (`@v4`) are matched; pinned SHAs and branch refs are not [1].

actionlint supports rich error reporting through **Go template formatting**, enabling one-line mode, JSON Lines output, GitHub Actions annotations (`::error file=...`), and SARIF. It ships with an official `actionlint-matcher.json` for GitHub's Problem Matcher integration [1]. On the Python side, `actionlint-py` [2] provides a pip-installable wrapper that downloads the Go binary, useful for pre-commit hooks, but **no native Python port exists**. For a Python-native validator, actionlint is best consumed as a subprocess rather than a library.

## 2. Schema validation covers structure but not semantics

**yamllint** [3] validates YAML formatting and style through ~20 configurable rules (indentation, duplicate keys, line length, truthy values, etc.) and outputs in `standard`, `colored`, `parsable`, or `github` annotation format. It catches what PyYAML's `safe_load()` misses — notably **duplicate keys**, which PyYAML silently resolves by taking the last value. However, yamllint performs zero semantic validation: it cannot tell whether `runs-on: ubuntu-latest` is valid or whether `needs: build` references a real job. Its value is strictly as a first-pass formatting gate [3].

The **SchemaStore community** maintains a JSON Schema (Draft-07) for GitHub Actions workflows at `https://json.schemastore.org/github-workflow.json` [4]. This schema covers triggers, jobs, steps, matrix strategies, permissions, concurrency, and reusable workflows. The Python tool **check-jsonschema** (v0.37.0) [5] by Stephen Rosen vendors this schema and provides both CLI validation and pre-commit hooks (`check-github-workflows`, `check-github-actions`). In Python, the `jsonschema` library can consume the schema directly via `Draft7Validator.iter_errors()` to collect all structural violations.

The schema's limitations are significant for a serious validator. It uses regex patterns to match `${{ }}` syntax but **cannot validate expression semantics** — no type-checking, no context availability verification, no function signature validation. It cannot verify `needs:` references, action inputs/outputs, or cron syntax. A comparison shows JSON Schema catches roughly **30% of common workflow errors** (structural mismatches), while actionlint catches **90%+** through deep semantic analysis [1][5].

**GitHub's own push-time validation** is a black box that rejects malformed YAML, invalid expression syntax, unrecognized top-level keys, and missing required structures (`on:`, `jobs:`, `runs-on:`). Runtime validation handles runner resolution, action availability, and permission enforcement. GitHub provides **no public validation API** and no official JSON Schema — the `gh` CLI has no validation command, though the `gh-actionlint` extension [6] bridges the gap.

## 3. Python validation libraries all lack native severity levels

Every major Python validation library — **pydantic**, **cerberus**, **marshmallow**, and **jsonschema** — implements a binary pass/fail model with no built-in concept of warning-level or info-level findings. Each can be adapted, but none provides multi-severity out of the box.

**Pydantic v2** [7] offers the most powerful structural validation through `@field_validator` and `@model_validator` decorators with before/after/wrap modes. It collects all errors into a single `ValidationError` containing typed error dicts with `loc` (path tuple), `msg`, `type`, and `ctx` fields. The `ValidationInfo.context` mechanism (set via `model_validate(data, context={})`) can be abused to inject a mutable list for collecting warnings, but this is a workaround, not a design pattern. Pydantic is best positioned as the **structural/type validation layer** that only produces hard errors.

**Cerberus** [8] processes the **entire document** before returning, making all errors accessible via `v.errors` (a dict mapping field names to error lists). Its subclassing model (`_validate_<rulename>` methods) makes it straightforward to add parallel `self.warnings` and `self.infos` dictionaries. **Marshmallow** [9] offers similar extensibility through its `context` dict and `@validates_schema` decorators. **jsonschema** [10] provides the richest error metadata — `iter_errors()` yields objects with `path`, `schema_path`, `validator`, and `validator_value` — making it ideal for post-processing errors into severity-tagged results based on which schema keyword failed.

The most flexible approach for a multi-severity CI validator is the **plain dataclass + custom validator pattern**: define a `Severity` enum (`ERROR`/`WARNING`/`INFO`), a `ValidationResult` dataclass, a `ValidationReport` collector, and a `ValidationRule` abstract base class. This costs more upfront but provides native severity, rule composition, configurable severity overrides, and format-agnostic output from the start — with zero library constraints [7].

## 4. ESLint's severity model is the one to borrow

Across pylint, ruff, flake8, and ESLint, a clear winner emerges for configurable severity. **ESLint's three-level system** — `"off"` (0), `"warn"` (1), `"error"` (2) — has precise, CI-friendly semantics: warnings are reported but produce exit code 0; errors produce exit code 1; disabled rules are never evaluated [11]. The `--max-warnings N` flag adds a threshold that fails CI when warning count exceeds N, enabling **gradual adoption** of new rules. Severity is configured separately from rule definition — rules just call `context.report()` and the config decides whether it's a warning or error.

**Ruff** [12] and **flake8** [13] use binary enabled/disabled models with no per-rule severity. **Pylint** [14] bakes severity into message IDs (the `C`/`W`/`E`/`F`/`R` prefix), making it non-configurable per project. None match ESLint's flexibility. However, ruff contributes a valuable pattern: **prefix-based rule grouping** (`E` for pycodestyle, `F` for Pyflakes, `SEC` for security) that enables enabling or disabling entire rule categories in one line.

Flake8's **entry-point-based plugin discovery** [13] offers the cleanest extensibility mechanism for Python: third-party packages register checkers via `setuptools` entry points, and Flake8 discovers them automatically at runtime. Code prefix namespacing prevents rule ID collisions between plugins. For a CI config validator, combining ESLint's severity model with flake8's entry-point plugin discovery and ruff's prefix grouping yields the best composite architecture.

## 5. CLI output should follow the rustc school of error design

Rust's compiler has set the standard for CLI error presentation [15]. The key elements are: severity label with color (red for errors, yellow for warnings), an **error code** for documentation lookup, file:line:col location, a **source snippet with caret underlines** pointing to the exact problem, primary and secondary labels explaining what went wrong and why, and actionable help suggestions with concrete replacement text.

Ruff demonstrates how to support **11 output formats** from a single tool: `full` (default with source context), `concise`, `grouped`, `json`, `json-lines`, `junit`, `github`, `gitlab`, `azure`, `sarif`, and `rdjson` [12]. For CI integration, the critical formats are GitHub Actions annotations and SARIF. GitHub annotations (`::error file=X,line=Y,col=Z::message`) support three levels (`error`, `warning`, `notice`) but impose harsh limits: **10 annotations per type per step** and **50 per job** [16]. For reports exceeding these limits, `GITHUB_STEP_SUMMARY` accepts up to **1 MiB of Markdown per step** with full table and diagram support, making it ideal for detailed validation reports [16].

SARIF (Static Analysis Results Interchange Format v2.1.0) [17] is the richest machine-readable format and is natively consumed by GitHub Code Scanning. Its structure separates tool metadata, rule definitions (with `defaultConfiguration.level`), and results (each with location, severity, and optional `fixes` array). For a validator that may integrate with multiple CI platforms, **SARIF should be the canonical output format** with simpler formats derived from it.

## 6. Fixability taxonomy follows a four-tier model

Cross-referencing ESLint's `fix`/`suggestions` split [11], Ruff's safe/unsafe/display-only classification [12], and Rust/Clippy's `MachineApplicable`/`MaybeIncorrect`/`HasPlaceholders`/`Unspecified` enum [15], a clear four-tier taxonomy emerges for issue fixability.

**Tier 1 — Safe auto-fix**: a single unambiguous correct fix that preserves semantics. For a CI validator, this includes adding a missing config key with a well-known default, removing duplicate YAML keys, or normalizing boolean values (`yes` → `true`). Applied with `--fix`.

**Tier 2 — Unsafe auto-fix** (opt-in): a likely-correct fix that may change behavior. This includes reordering steps for topological correctness (might break intentional ordering), adding restrictive `permissions:` blocks, or updating deprecated action versions. Applied only with `--fix --unsafe-fixes`.

**Tier 3 — Suggested fix**: the tool shows what the fix looks like but the user must choose or adapt. Multiple valid options may exist. This includes rewriting a `run:` step to use a dedicated action (which action?), adding caching strategies (project-specific cache keys), or splitting a monolithic job.

**Tier 4 — Requires human judgment**: the tool identifies the problem but cannot suggest a concrete fix. This includes whether a `run:` step should be refactored into a reusable action (an architectural decision), whether `needs:` dependencies reflect the correct execution graph, or whether conditional logic correctly guards steps.

Ruff's `applicability` field in JSON output is the cleanest implementation of this taxonomy — every fix carries an explicit safety label [12]. ESLint communicates fixability in its summary line: `"2 errors and 1 warning potentially fixable with the --fix option"` and separates `fix` (auto-applicable) from `suggestions[]` (user-selectable alternatives) in its JSON format [11].

## 7. LLM integration is emerging but immature

The intersection of static analysis and LLM-based review is nascent. **CodeRabbit** combines AST-Grep pattern matching with LLM analysis for PR reviews. **GPTLint** [18] uses OpenAI to enforce natural-language rules that traditional static analysis cannot express. Academic research identifies **Retrieval-Augmented Generation (RAG)** — feeding static analysis findings to an LLM at inference time — as the most effective hybrid approach [19].

For a CI config validator, the practical integration point is Tier 4 issues: findings flagged as "requires human judgment" can optionally be passed to an LLM agent with the specific code context, the rule that flagged it, and project conventions. The LLM provides contextual suggestions posted as visually distinct annotations (e.g., prefixed with 🤖). The key design principle is to **keep deterministic and AI-generated findings strictly separated** in both the data model and the UI, since they have fundamentally different reliability profiles.

## Conclusion

The recommended architecture for a CI recipe validator layers three systems. First, a **structural layer** using `jsonschema` with the SchemaStore schema (or pydantic models) catches type errors and missing required fields — producing hard errors only. Second, a **semantic rule layer** using the dataclass + custom validator pattern implements domain-specific checks (data flow sourcing, DAG acyclicity, purity contracts, config completeness) with ESLint-style configurable severity and flake8-style entry-point plugin discovery. Third, an **output layer** generates SARIF as the canonical format, with derived GitHub annotations, CLI-formatted output (following rustc conventions), and step summary markdown. Each finding carries an explicit four-tier fixability classification.

The non-obvious insight is that actionlint already solves many of the hard problems — expression type-checking, cycle detection, action schema validation — and should be invoked as a subprocess rather than reimplemented. The Python validator's unique value lies in the domain-specific rules that no existing tool checks: whether all step inputs have explicit sources, whether `run:` steps violate typed contracts, and whether the project's config file satisfies the recipe's declared requirements.

---

## References

[1] rhysd, "actionlint — Static checker for GitHub Actions workflow files," GitHub, 2024. https://github.com/rhysd/actionlint

[2] M. Grzelinski, "actionlint-py — Python wrapper for actionlint," GitHub, 2024. https://github.com/Mateusz-Grzelinski/actionlint-py

[3] A. Vergé, "yamllint — A linter for YAML files," GitHub, 2024. https://github.com/adrienverge/yamllint

[4] SchemaStore contributors, "GitHub Workflow JSON Schema," SchemaStore, 2024. https://json.schemastore.org/github-workflow.json

[5] S. Rosen, "check-jsonschema — A CLI and set of pre-commit hooks for jsonschema validation," GitHub, 2024. https://github.com/python-jsonschema/check-jsonschema

[6] C. Schleiden, "gh-actionlint — GitHub CLI extension for actionlint," GitHub, 2023. https://github.com/cschleiden/gh-actionlint

[7] Pydantic contributors, "Pydantic v2 documentation — Validators," 2024. https://docs.pydantic.dev/latest/concepts/validators/

[8] N. Colomer, "Cerberus — Lightweight, extensible data validation library for Python," 2024. https://docs.python-cerberus.org/

[9] S. Loria et al., "marshmallow — An ORM/ODM/framework-agnostic library for converting complex datatypes," 2024. https://marshmallow.readthedocs.io/

[10] J. Carrick et al., "jsonschema — An implementation of JSON Schema for Python," 2024. https://python-jsonschema.readthedocs.io/

[11] ESLint contributors, "ESLint — Pluggable JavaScript linter," 2024. https://eslint.org/docs/latest/use/configure/rules

[12] Astral Software Inc., "Ruff — An extremely fast Python linter and code formatter," 2024. https://docs.astral.sh/ruff/

[13] I. Stapleton Cordasco et al., "Flake8 — Your tool for style guide enforcement," 2024. https://flake8.pycqa.org/

[14] Pylint contributors, "Pylint — Python code static checker," 2024. https://pylint.readthedocs.io/en/latest/development_guide/how_tos/custom_checkers.html

[15] Rust contributors, "The Rust compiler error index and Clippy documentation," 2024. https://doc.rust-lang.org/error_codes/

[16] GitHub, "Workflow commands for GitHub Actions," GitHub Docs, 2024. https://docs.github.com/en/actions/using-workflows/workflow-commands-for-github-actions

[17] OASIS, "Static Analysis Results Interchange Format (SARIF) Version 2.1.0," 2024. https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html

[18] GPTLint contributors, "GPTLint — Use LLMs to enforce best practices across your codebase," GitHub, 2024. https://github.com/gptlint/gptlint

[19] L. Li et al., "Enhancing static analysis with LLM-based techniques: A survey," arXiv, 2024. https://arxiv.org/abs/2405.00311