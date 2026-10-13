# reci.validation.formatters

Output formatters for validation reports.

### Functions

| [`format_cli`](#reci.validation.formatters.format_cli)(report)                | Human-readable CLI output with color-coded severity.   |
|------------------------------------------------------------------------------------|--------------------------------------------------------|
| [`format_github_annotations`](#reci.validation.formatters.format_github_annotations)(report) | GitHub Actions annotation format.                      |
| [`format_json`](#reci.validation.formatters.format_json)(report)               | JSON output: list of finding dicts.                    |

### reci.validation.formatters.format_cli(report)

Human-readable CLI output with color-coded severity.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### reci.validation.formatters.format_github_annotations(report)

GitHub Actions annotation format.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### reci.validation.formatters.format_json(report)

JSON output: list of finding dicts.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
