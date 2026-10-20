# reci.validation.report

Core validation data structures.

### Classes

| [`Finding`](#reci.validation.report.Finding)(rule_id, severity, message[, ...])   | One validation finding.            |
|-----------------------------------------------------------------------------------------------|------------------------------------|
| [`Severity`](#reci.validation.report.Severity)(\*values)                           | ESLint-style three-level severity. |
| [`ValidationReport`](#reci.validation.report.ValidationReport)([findings])                 | Collection of validation findings. |

### *class* reci.validation.report.Finding(rule_id, severity, message, location=None, suggestion=None, fixable=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One validation finding.

### *class* reci.validation.report.Severity(\*values)

Bases: [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

ESLint-style three-level severity.

### *class* reci.validation.report.ValidationReport(findings=list())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Collection of validation findings.
