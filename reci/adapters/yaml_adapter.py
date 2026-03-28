"""YamlAdapter — reads ``.ci.yml`` via ruamel.yaml."""

from __future__ import annotations

from typing import Any

from reci.adapters.pyproject import _flatten
from reci.yaml_gen import load_yaml, _make_yaml


class YamlAdapter:
    """Read/write CI config from a ``.ci.yml`` file."""

    def read(self, path: str) -> dict[str, Any]:
        data = load_yaml(path)
        if not isinstance(data, dict):
            return {}
        return _flatten(data)

    def write(self, path: str, config: dict[str, Any]) -> None:
        y = _make_yaml()
        with open(path, 'w') as f:
            y.dump(config, f)

    def default_path(self) -> str:
        return '.ci.yml'
