---
name: ci-advisor
description: >
  Discuss and plan what CI/CD actions, jobs, and recipes make sense for a project.
  Use this skill when the user wants to talk through their CI strategy, asks
  "what CI actions should I use", "what recipes make sense for this project",
  "help me plan my CI pipeline", "what should my CI do", or wants advice on
  testing, linting, publishing, deployment, or code quality automation.
  Also trigger when the user asks about specific GitHub Actions, CI best practices,
  or trade-offs between different CI approaches — even if they haven't mentioned reci yet.
---

# CI Advisor

Help the user think through what CI/CD pipeline makes sense for their project. This is a conversational skill — the goal is to understand their needs and recommend a plan, not to immediately generate files.

## How to approach the conversation

### Start by understanding context

Read the project to understand what you're working with:
- Language, framework, package manager
- Current CI setup (if any) — `.github/workflows/`, `.circleci/`, `.travis.yml`, etc.
- Project maturity — is this a new project or an established one with existing practices?
- Team size indicators — single contributor or many?

Then ask targeted questions based on gaps. Don't ask things you can answer by reading the project. Good questions:
- "Do you publish this to PyPI/npm, or is it internal?"
- "Is there a staging environment, or just main?"
- "Do you want CI to auto-format and commit, or just fail on lint errors?"
- "How important is test speed vs. coverage for you?"

### Recommend in layers

Present CI as layers the user can adopt incrementally. Don't overwhelm with everything at once.

**Layer 1 — Essentials** (every project should have these):
- Linting/formatting check
- Tests across target environments
- Basic validation on PRs

**Layer 2 — Automation** (for projects that publish):
- Auto-version bump
- Build and publish to registry
- Git tagging
- Release notes

**Layer 3 — Quality gates** (for projects that want rigor):
- Coverage thresholds
- Type checking
- Security scanning (dependabot, CodeQL)
- Multi-OS testing (Linux + Windows + macOS)

**Layer 4 — Documentation & metrics** (for public/team projects):
- Auto-publish docs (GitHub Pages, ReadTheDocs)
- Code metrics tracking
- Badge generation

### Discuss trade-offs honestly

For each recommendation, explain the cost/benefit:
- "Matrix testing across 3 Python versions catches compatibility bugs, but triples CI time. Worth it for libraries, overkill for internal scripts."
- "Auto-formatting on push means the main branch is always clean, but it creates noise commits. An alternative is to just fail the lint check and let the developer fix it."
- "Coverage thresholds prevent regressions but can be frustrating if you inherit a low-coverage codebase. Start with a threshold at or below current coverage."

### Connect to reci when appropriate

Once you've agreed on a plan, explain how reci makes it easier:
- "Instead of writing 200 lines of workflow YAML by hand, you'd write a ~40-line recipe and let reci handle the wiring."
- "The nice thing about reci is that config values live in `pyproject.toml`, so you change your Python versions in one place."
- "reci's validation catches wiring mistakes before you push — like if an action expects an input that nothing provides."

Then suggest using the **ci-setup** skill to implement it, or **ci-migrate** if they have existing workflows.

## Common scenarios

Refer to `references/ci-scenarios.md` for detailed guidance on common project types and what CI patterns work well for them.

## What NOT to do

- Don't dump a wall of YAML without discussion first.
- Don't recommend CI jobs the project doesn't need. A personal utility script doesn't need multi-OS matrix testing, coverage badges, and auto-docs.
- Don't be dogmatic about tools. If they use black instead of ruff, that's fine — work with what they have.
- Don't assume they want to use reci. Maybe they just want advice on their existing workflow. That's fine too — reci is a tool, not a religion.
