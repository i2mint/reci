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
    that leaf; a new key whose ``__`` prefix names an existing table
    (``testing__new``) is added inside it (never over a table of that name); any other key is stored flat.
    :func:`flatten` reads all of these back as the same key.  Existing keys that
    *flat* does not mention are left alone.

    >>> t = {'testing': {'coverage': True}}
    >>> merge_flat(t, {'testing__coverage': False, 'testing__new': 2, 'new': 1})
    >>> t
    {'testing': {'coverage': False, 'new': 2}, 'new': 1}
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
            _set_new(target, key, value)


def _set_new(target: MutableMapping, key: str, value: Any) -> None:
    """Store a new *key* in the deepest existing table its ``__`` prefix names.

    ``testing__new`` goes inside ``[testing]`` when that table exists, else it is
    stored flat; :func:`flatten` reads both back as the same key.  A table that is a
    YAML anchor (or an alias of one) is skipped, since a write into it would also
    change every other place that shares it.
    """
    parts = key.split("__")
    for end in range(len(parts) - 1, 0, -1):
        node: Any = target
        shared = False
        for part in parts[:end]:
            node = node.get(part) if isinstance(node, dict) else None
            shared = shared or _is_shared(node)
        if shared:
            continue
        rest = "__".join(parts[end:])
        # Never overwrite a table: that would drop the leaves flattened under it
        if isinstance(node, dict) and not isinstance(node.get(rest), dict):
            node[rest] = value
            return
    target[key] = value


def _is_shared(node: Any) -> bool:
    """Is *node* a YAML mapping carrying an anchor (so it may be aliased elsewhere)?"""
    return getattr(getattr(node, "anchor", None), "value", None) is not None
