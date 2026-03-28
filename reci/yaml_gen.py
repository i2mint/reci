"""YAML I/O wrapper using ruamel.yaml (YAML 1.2).

Handles the critical ``on:`` key (PyYAML treats it as boolean True),
wraps ``${{ }}`` expressions in SingleQuotedScalarString, and uses
LiteralScalarString for multiline ``run:`` blocks.
"""

from __future__ import annotations

import io
import re
from typing import Any, TextIO

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import (
    LiteralScalarString,
    SingleQuotedScalarString,
)

_EXPRESSION_RE = re.compile(r"\$\{\{.*?\}\}")


def _make_yaml() -> YAML:
    """Factory for a configured ruamel.yaml instance."""
    y = YAML()
    y.default_flow_style = False
    y.width = 120
    y.indent(mapping=2, sequence=4, offset=2)
    y.preserve_quotes = True
    return y


def load_yaml(path: str) -> dict:
    """Load a YAML file and return a plain dict."""
    y = _make_yaml()
    with open(path) as f:
        return y.load(f)


def load_yaml_string(text: str) -> dict:
    """Load YAML from a string and return a plain dict."""
    y = _make_yaml()
    return y.load(text)


def dump_workflow(workflow: dict, *, stream: TextIO | None = None) -> str | None:
    """Serialize a workflow dict to GitHub Actions YAML.

    If *stream* is ``None``, returns the YAML string.  Otherwise writes to
    *stream* and returns ``None``.
    """
    prepared = _prepare_workflow_dict(workflow)
    y = _make_yaml()
    if stream is None:
        buf = io.StringIO()
        y.dump(prepared, buf)
        return buf.getvalue()
    y.dump(prepared, stream)
    return None


def _prepare_workflow_dict(d: Any) -> Any:
    """Recursively wrap values for correct YAML output.

    - Strings containing ``${{ }}`` -> ``SingleQuotedScalarString``
    - Multiline strings (containing newlines) -> ``LiteralScalarString``
    """
    if isinstance(d, dict):
        return {k: _prepare_workflow_dict(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_prepare_workflow_dict(v) for v in d]
    if isinstance(d, str):
        if "\n" in d:
            return LiteralScalarString(d)
        if _EXPRESSION_RE.search(d):
            return SingleQuotedScalarString(d)
    return d
