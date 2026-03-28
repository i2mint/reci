"""Validation rule registry and runner."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from reci.validation.report import Finding, Severity, ValidationReport

RuleFunc = Callable[..., Iterable[Finding]]

_RULES: dict[str, RuleFunc] = {}


def register_rule(rule_id: str):
    """Decorator to register a validation rule function."""

    def decorator(fn: RuleFunc) -> RuleFunc:
        _RULES[rule_id] = fn
        return fn

    return decorator


# Import rule modules to trigger registration
def _ensure_rules_loaded() -> None:
    from reci.validation.rules import dag, flow, config_rules, purity, action  # noqa: F401


def run_all_rules(
    graph,
    config: dict[str, Any],
    *,
    severity_overrides: dict[str, str] | None = None,
    disabled_rules: set[str] | None = None,
) -> ValidationReport:
    """Run all registered rules and return a merged report."""
    _ensure_rules_loaded()
    severity_overrides = severity_overrides or {}
    disabled_rules = disabled_rules or set()

    findings: list[Finding] = []
    for rule_id, fn in _RULES.items():
        if rule_id in disabled_rules:
            continue
        for finding in fn(graph, config):
            # Apply severity override
            if finding.rule_id in severity_overrides:
                override = severity_overrides[finding.rule_id]
                if override == 'off':
                    continue
                finding = Finding(
                    rule_id=finding.rule_id,
                    severity=Severity(override),
                    message=finding.message,
                    location=finding.location,
                    suggestion=finding.suggestion,
                    fixable=finding.fixable,
                )
            findings.append(finding)

    return ValidationReport(findings=findings)
