"""PackageJsonAdapter — reads ``"ci"`` key from package.json."""

from __future__ import annotations

import json
from typing import Any

from reci.adapters.pyproject import _flatten


class PackageJsonAdapter:
    """Read/write CI config from ``"ci"`` key in package.json."""

    def read(self, path: str) -> dict[str, Any]:
        with open(path) as f:
            data = json.load(f)
        return _flatten(data.get("ci", {}))

    def write(self, path: str, config: dict[str, Any]) -> None:
        with open(path) as f:
            data = json.load(f)
        data["ci"] = config
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")

    def default_path(self) -> str:
        return "package.json"
