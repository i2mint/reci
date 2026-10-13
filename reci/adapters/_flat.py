"""Flat <-> nested config helpers shared by the adapters.

Config is exposed to the rest of reci as a flat dict whose keys join nested
table names with ``__`` (``[tool.ci.testing] coverage`` -> ``testing__coverage``).
Writing must be the inverse: update the nested leaf where one exists, rather
than adding a second, flat copy next to it.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any


def flatten(d: dict, *, prefix: str = "") -> dict[str, Any]:
    """Flatten a nested dict using ``__`` as separator.

    >>> flatten({'a': {'b': 1}, 'c': 2})
    {'a__b': 1, 'c': 2}
    """
    return {key: d_value for key, (_, d_value) in _leaves(d, prefix=prefix).items()}


def _leaves(
    d: dict, *, prefix: str = "", path: tuple[str, ...] = ()
) -> dict[str, tuple[tuple[str, ...], Any]]:
    """``{flat_key: (path_to_leaf, value)}`` for every non-dict value in *d*."""
    result: dict[str, tuple[tuple[str, ...], Any]] = {}
    for k, v in d.items():
        full_key = f"{prefix}__{k}" if prefix else str(k)
        if isinstance(v, dict):
            result.update(_leaves(v, prefix=full_key, path=(*path, k)))
        else:
            result[full_key] = ((*path, k), v)
    return result


def merge_flat(target: MutableMapping, flat: dict[str, Any]) -> None:
    """Merge a flat config into the nested mapping *target*, in place.

    A key that matches an existing nested leaf (``testing__coverage``) updates
    that leaf; any other key (including a brand-new ``a__b``) is stored flat,
    which :func:`flatten` reads back as the same key.  Existing keys that
    *flat* does not mention are left alone.

    >>> t = {'testing': {'coverage': True}}
    >>> merge_flat(t, {'testing__coverage': False, 'new': 1})
    >>> t
    {'testing': {'coverage': False}, 'new': 1}
    """
    leaves = _leaves(target)
    for key, value in flat.items():
        if key in leaves:
            *parents, last = leaves[key][0]
            node = target
            for part in parents:
                node = node[part]
            node[last] = value
        else:
            target[key] = value
