"""Action metadata validation rules (ACT001–ACT003)."""

from __future__ import annotations

from typing import Any, Iterable

from reci.validation.report import Finding, Severity
from reci.validation.rules import register_rule


@register_rule('ACT002')
def check_action_not_found(graph, config: dict[str, Any]) -> Iterable[Finding]:
    """Referenced action has no ActionSpec (could not be fetched or parsed)."""
    for node in graph.nodes():
        if node.ref and node.action_spec is None:
            yield Finding(
                rule_id='ACT002',
                severity=Severity.ERROR,
                message=(
                    f"Action '{node.ref}' referenced by '{node.key}' "
                    f"could not be resolved. No action spec available."
                ),
                location=node.key,
            )
