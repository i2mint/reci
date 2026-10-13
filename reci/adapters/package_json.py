"""PackageJsonAdapter — reads ``"ci"`` key from package.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from reci.adapters._flat import flatten as _flatten, merge_flat


class PackageJsonAdapter:
    """Read/write CI config from ``"ci"`` key in package.json."""

    def read(self, path: str) -> dict[str, Any]:
        with open(path) as f:
            data = json.load(f)
        return _flatten(data.get("ci") or {})

    def write(self, path: str, config: dict[str, Any]) -> None:
        if Path(path).exists():
            with open(path) as f:
                data = json.load(f)
        else:
            data = {}
        if not isinstance(data.get("ci"), dict):  # missing or null
            data["ci"] = {}
        merge_flat(data["ci"], config)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")

    def default_path(self) -> str:
        return "package.json"
