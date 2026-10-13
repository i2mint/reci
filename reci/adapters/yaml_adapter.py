"""YamlAdapter — reads ``.ci.yml`` via ruamel.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reci.adapters._flat import flatten as _flatten, merge_flat
from reci.yaml_gen import load_yaml, _make_yaml


class YamlAdapter:
    """Read/write CI config from a ``.ci.yml`` file."""

    def read(self, path: str) -> dict[str, Any]:
        data = load_yaml(path)
        if not isinstance(data, dict):
            return {}
        return _flatten(data)

    def write(self, path: str, config: dict[str, Any]) -> None:
        existing = load_yaml(path) if Path(path).exists() else None
        data = existing if isinstance(existing, dict) else {}
        merge_flat(data, config)
        with open(path, "w") as f:
            _make_yaml().dump(data, f)

    def default_path(self) -> str:
        return ".ci.yml"
