"""ConfigAdapter protocol — interface for reading/writing CI config."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ConfigAdapter(Protocol):
    """Protocol for pluggable CI config I/O."""

    def read(self, path: str) -> dict[str, Any]:
        """Read config from a file and return a flat dict."""
        ...

    def write(self, path: str, config: dict[str, Any]) -> None:
        """Write config to a file, preserving existing content."""
        ...

    def default_path(self) -> str:
        """Return the default filename for this adapter."""
        ...
