"""Core validation data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(Enum):
    """ESLint-style three-level severity."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Finding:
    """One validation finding."""

    rule_id: str
    severity: Severity
    message: str
    location: str | None = None
    suggestion: str | None = None
    fixable: bool = False


@dataclass
class ValidationReport:
    """Collection of validation findings."""

    findings: list[Finding] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(f.severity is Severity.ERROR for f in self.findings)

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity is Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity is Severity.WARNING)

    def findings_by_severity(self, severity: Severity) -> list[Finding]:
        return [f for f in self.findings if f.severity is severity]

    def findings_by_rule(self, rule_prefix: str) -> list[Finding]:
        return [f for f in self.findings if f.rule_id.startswith(rule_prefix)]

    def merge(self, other: ValidationReport) -> ValidationReport:
        return ValidationReport(findings=self.findings + other.findings)
