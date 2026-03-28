"""Config adapter registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reci.adapters.base import ConfigAdapter


def get_adapter(name: str) -> ConfigAdapter:
    """Get a config adapter by name."""
    if name == 'pyproject':
        from reci.adapters.pyproject import PyprojectTomlAdapter
        return PyprojectTomlAdapter()
    if name == 'wads':
        from reci.adapters.wads import WadsAdapter
        return WadsAdapter()
    if name == 'package-json':
        from reci.adapters.package_json import PackageJsonAdapter
        return PackageJsonAdapter()
    if name == 'yaml':
        from reci.adapters.yaml_adapter import YamlAdapter
        return YamlAdapter()
    raise ValueError(f"Unknown config adapter: '{name}'")


def detect_adapter(project_root: str) -> ConfigAdapter | None:
    """Auto-detect the config adapter from project files."""
    root = Path(project_root)
    if (root / 'pyproject.toml').exists():
        from reci.adapters.pyproject import PyprojectTomlAdapter
        return PyprojectTomlAdapter()
    if (root / 'package.json').exists():
        from reci.adapters.package_json import PackageJsonAdapter
        return PackageJsonAdapter()
    if (root / '.ci.yml').exists():
        from reci.adapters.yaml_adapter import YamlAdapter
        return YamlAdapter()
    return None
