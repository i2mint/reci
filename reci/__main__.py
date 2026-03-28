"""CLI entry point — ``python -m reci`` or ``reci`` command."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import argh

from reci.action_spec import action_spec_from_ref, ActionSpec, ActionFetchError
from reci.recipe import parse_recipe, RecipeParseError
from reci.graph import RecipeGraph
from reci.compiler import compile_recipe
from reci.config import collect_required_config_keys
from reci.yaml_gen import dump_workflow
from reci.validation.formatters import (
    format_cli,
    format_json,
    format_github_annotations,
)
from reci.adapters import get_adapter, detect_adapter


def _load_config(
    *,
    config_adapter: str = 'pyproject',
    config_path: str | None = None,
) -> dict[str, Any]:
    adapter = get_adapter(config_adapter)
    path = config_path or adapter.default_path()
    if not Path(path).exists():
        return {}
    return adapter.read(path)


def _fetch_specs(recipe) -> dict[str, ActionSpec]:
    specs: dict[str, ActionSpec] = {}
    for job in recipe.jobs.values():
        for step in job.steps:
            if step.uses and step.uses not in specs:
                try:
                    specs[step.uses] = action_spec_from_ref(step.uses)
                except ActionFetchError as e:
                    print(f'warning: {e}', file=sys.stderr)
    return specs


def compile(
    recipe: str,
    *,
    config_adapter: str = 'pyproject',
    config_path: str | None = None,
    output: str = '.github/workflows/ci.yml',
) -> None:
    """Compile a recipe into a GitHub Actions workflow YAML."""
    rec = parse_recipe(recipe)
    specs = _fetch_specs(rec)
    config = _load_config(config_adapter=config_adapter, config_path=config_path)

    workflow = compile_recipe(rec, specs, config=config)

    # Validate and print warnings
    graph = RecipeGraph.from_recipe(rec, specs)
    report = graph.validate(config)
    if report.findings:
        print(format_cli(report), file=sys.stderr)
    if report.has_errors:
        print('Compilation aborted due to errors.', file=sys.stderr)
        sys.exit(1)

    # Write output
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w') as f:
        dump_workflow(workflow, stream=f)
    print(f'Wrote {out_path}')


def validate(
    *,
    recipe: str = 'recipe.yml',
    config_adapter: str = 'pyproject',
    config_path: str | None = None,
    format: str = 'cli',
    max_warnings: int = -1,
) -> None:
    """Validate recipe and config for correctness."""
    rec = parse_recipe(recipe)
    specs = _fetch_specs(rec)
    config = _load_config(config_adapter=config_adapter, config_path=config_path)

    graph = RecipeGraph.from_recipe(rec, specs)
    report = graph.validate(config)

    # Format output
    formatter = {
        'cli': format_cli,
        'json': format_json,
        'github': format_github_annotations,
    }.get(format, format_cli)
    print(formatter(report))

    # Exit code
    if report.has_errors:
        sys.exit(1)
    if max_warnings >= 0 and report.warning_count > max_warnings:
        print(
            f'Too many warnings: {report.warning_count} '
            f'(max {max_warnings})',
            file=sys.stderr,
        )
        sys.exit(1)


def scaffold(
    recipe: str,
    *,
    config_adapter: str = 'pyproject',
    config_path: str | None = None,
    output: str = '.github/workflows/ci.yml',
) -> None:
    """Generate workflow YAML and config skeleton."""
    rec = parse_recipe(recipe)
    specs = _fetch_specs(rec)
    required = collect_required_config_keys(rec, specs)

    adapter = get_adapter(config_adapter)
    path = config_path or adapter.default_path()

    # Read existing config or start fresh
    existing = adapter.read(path) if Path(path).exists() else {}
    for key, is_required in required.items():
        if key not in existing:
            existing[key] = f'<REQUIRED: {key}>' if is_required else ''

    adapter.write(path, existing)
    print(f'Updated config: {path}')

    # Compile with skeleton config
    workflow = compile_recipe(rec, specs, config=existing)
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w') as f:
        dump_workflow(workflow, stream=f)
    print(f'Wrote {out_path}')


def inspect(action_ref: str) -> None:
    """Fetch and display an action's input/output contract."""
    spec = action_spec_from_ref(action_ref)
    print(f'Action: {spec.ref}\n')

    if spec.inputs:
        print('Inputs:')
        for inp in spec.inputs.values():
            req = ' (required)' if inp.required else ''
            default = f' [default: {inp.default}]' if inp.default else ''
            print(f'  {inp.name}{req}{default}')
            if inp.description:
                print(f'    {inp.description}')
    else:
        print('Inputs: none')

    print()
    if spec.outputs:
        print('Outputs:')
        for out in spec.outputs.values():
            print(f'  {out.name}')
            if out.description:
                print(f'    {out.description}')
    else:
        print('Outputs: none')


def main():
    argh.dispatch_commands([compile, validate, scaffold, inspect])


if __name__ == '__main__':
    main()
