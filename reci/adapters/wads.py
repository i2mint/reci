"""WadsAdapter — reads ``[tool.wads.ci]`` for backward compatibility."""

from __future__ import annotations

from typing import Any

from reci.adapters.pyproject import PyprojectTomlAdapter


class WadsAdapter(PyprojectTomlAdapter):
    """Read/write CI config from ``[tool.wads.ci]`` in pyproject.toml."""

    _section_path: tuple[str, ...] = ('tool', 'wads', 'ci')
