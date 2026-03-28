"""PyprojectTomlAdapter — reads ``[tool.ci]`` via tomlkit, round-trip preserving."""

from __future__ import annotations

from typing import Any

import tomlkit


class PyprojectTomlAdapter:
    """Read/write CI config from ``[tool.ci]`` in pyproject.toml."""

    _section_path: tuple[str, ...] = ("tool", "ci")

    def read(self, path: str) -> dict[str, Any]:
        with open(path) as f:
            doc = tomlkit.load(f)
        section = doc
        for key in self._section_path:
            section = section.get(key, {})
        return _flatten(dict(section))

    def write(self, path: str, config: dict[str, Any]) -> None:
        with open(path) as f:
            doc = tomlkit.load(f)

        # Navigate to parent, creating sections as needed
        parent = doc
        for key in self._section_path[:-1]:
            if key not in parent:
                parent[key] = tomlkit.table()
            parent = parent[key]

        last_key = self._section_path[-1]
        if last_key not in parent:
            parent[last_key] = tomlkit.table()

        section = parent[last_key]
        for k, v in config.items():
            section[k] = v

        with open(path, "w") as f:
            tomlkit.dump(doc, f)

    def default_path(self) -> str:
        return "pyproject.toml"


def _flatten(d: dict, *, prefix: str = "") -> dict[str, Any]:
    """Flatten a nested dict using ``__`` as separator."""
    result: dict[str, Any] = {}
    for k, v in d.items():
        full_key = f"{prefix}{k}" if not prefix else f"{prefix}__{k}"
        if isinstance(v, dict):
            result.update(_flatten(v, prefix=full_key))
        else:
            result[full_key] = v
    return result
