"""Output formatters for validation reports."""

from __future__ import annotations

import json
from typing import Any

from reci.validation.report import Finding, Severity, ValidationReport

# ANSI color codes
_COLORS = {
    Severity.ERROR: '\033[91m',    # red
    Severity.WARNING: '\033[93m',  # yellow
    Severity.INFO: '\033[94m',     # blue
}
_RESET = '\033[0m'


def format_cli(report: ValidationReport) -> str:
    """Human-readable CLI output with color-coded severity."""
    if not report.findings:
        return 'No issues found.'

    lines: list[str] = []
    for f in report.findings:
        color = _COLORS.get(f.severity, '')
        prefix = f'{color}{f.severity.value}{_RESET}'
        line = f'{prefix} {f.rule_id}: {f.message}'
        if f.location:
            line += f'\n  --> {f.location}'
        if f.suggestion:
            line += f'\n  = help: {f.suggestion}'
        lines.append(line)

    # Summary
    e = report.error_count
    w = report.warning_count
    summary = f'\n{e} error(s), {w} warning(s), {len(report.findings)} total'
    lines.append(summary)
    return '\n'.join(lines)


def format_json(report: ValidationReport) -> str:
    """JSON output: list of finding dicts."""
    items = [
        {
            'rule_id': f.rule_id,
            'severity': f.severity.value,
            'message': f.message,
            'location': f.location,
            'suggestion': f.suggestion,
            'fixable': f.fixable,
        }
        for f in report.findings
    ]
    return json.dumps(items, indent=2)


def format_github_annotations(report: ValidationReport) -> str:
    """GitHub Actions annotation format."""
    lines: list[str] = []
    for f in report.findings:
        level = 'error' if f.severity is Severity.ERROR else 'warning'
        if f.severity is Severity.INFO:
            level = 'notice'
        msg = f'[{f.rule_id}] {f.message}'
        if f.location:
            lines.append(f'::{level} file={f.location}::{msg}')
        else:
            lines.append(f'::{level}::{msg}')
    return '\n'.join(lines)
