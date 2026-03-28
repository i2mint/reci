"""Purity validation rules (PURE001–PURE003)."""

from __future__ import annotations

import re
from typing import Any, Iterable

from reci.validation.report import Finding, Severity
from reci.validation.rules import register_rule

_GITHUB_OUTPUT_RE = re.compile(r'>>\s*[\"\']?\$\{?GITHUB_OUTPUT\}?[\"\']?')
_EXPRESSION_RE = re.compile(r'\$\{\{.*?\}\}')


@register_rule('PURE001')
def check_run_steps(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """Any run: step breaks the typed data-flow contract."""
    for node in graph.nodes():
        if node.run is not None:
            yield Finding(
                rule_id='PURE001',
                severity=Severity.WARNING,
                message=(
                    f"Step '{node.key}' uses an inline 'run:' script. "
                    f"This breaks the typed data-flow contract."
                ),
                location=node.key,
                suggestion=(
                    'Consider refactoring into a composite action '
                    'with typed inputs/outputs.'
                ),
            )


@register_rule('PURE002')
def check_run_step_outputs(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """A run: step writes to $GITHUB_OUTPUT."""
    for node in graph.nodes():
        if node.run and _GITHUB_OUTPUT_RE.search(node.run):
            if not node.declared_outputs:
                yield Finding(
                    rule_id='PURE002',
                    severity=Severity.INFO,
                    message=(
                        f"Step '{node.key}' writes to $GITHUB_OUTPUT "
                        f"but has no declared outputs in the recipe."
                    ),
                    location=node.key,
                    suggestion=(
                        "Declare outputs in the recipe: "
                        "outputs: [name1, name2]"
                    ),
                )
