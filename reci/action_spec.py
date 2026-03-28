"""Action contract model — parsed from ``action.yml`` metadata.

An :class:`ActionSpec` captures the typed input/output contract of a GitHub
Action so that downstream modules (graph, compiler, validation) can reason
about data flow without fetching YAML at every step.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from reci.yaml_gen import load_yaml_string

# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

_NORMALIZE_RE = re.compile(r"[-\s]+")


def normalize_name(name: str) -> str:
    """Canonical form: lowercase, hyphens/spaces → underscores.

    >>> normalize_name('python-version')
    'python_version'
    >>> normalize_name('Root Dir')
    'root_dir'
    """
    return _NORMALIZE_RE.sub("_", name.strip().lower())


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InputSpec:
    """One declared input of a GitHub Action."""

    name: str  # normalized
    required: bool = False
    default: str | None = None
    description: str = ""


@dataclass(frozen=True)
class OutputSpec:
    """One declared output of a GitHub Action."""

    name: str  # normalized
    description: str = ""


@dataclass(frozen=True)
class ActionSpec:
    """The typed contract of a single GitHub Action.

    *inputs* and *outputs* are keyed by **normalized** name.
    """

    ref: str
    inputs: dict[str, InputSpec] = field(default_factory=dict)
    outputs: dict[str, OutputSpec] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "yes", "1")
    return bool(value)


def parse_action_spec(ref: str, *, action_yml_data: dict) -> ActionSpec:
    """Build an :class:`ActionSpec` from a ref string and parsed action.yml data."""
    inputs: dict[str, InputSpec] = {}
    for name, meta in (action_yml_data.get("inputs") or {}).items():
        meta = meta or {}
        norm = normalize_name(name)
        inputs[norm] = InputSpec(
            name=norm,
            required=_parse_bool(meta.get("required", False)),
            default=meta.get("default"),
            description=str(meta.get("description", "")),
        )

    outputs: dict[str, OutputSpec] = {}
    for name, meta in (action_yml_data.get("outputs") or {}).items():
        meta = meta or {}
        norm = normalize_name(name)
        outputs[norm] = OutputSpec(
            name=norm,
            description=str(meta.get("description", "")),
        )

    return ActionSpec(ref=ref, inputs=inputs, outputs=outputs)


# ---------------------------------------------------------------------------
# Fetching from GitHub
# ---------------------------------------------------------------------------


def _parse_ref(ref: str) -> tuple[str, str, str, str]:
    """Split ``owner/repo/path@tag`` into (owner, repo, subpath, tag).

    >>> _parse_ref('i2mint/wads/actions/run-tests@master')
    ('i2mint', 'wads', 'actions/run-tests', 'master')
    >>> _parse_ref('actions/checkout@v4')
    ('actions', 'checkout', '', 'v4')
    """
    at_parts = ref.split("@", 1)
    tag = at_parts[1] if len(at_parts) > 1 else "main"
    path_parts = at_parts[0].split("/", 2)
    owner = path_parts[0]
    repo = path_parts[1] if len(path_parts) > 1 else ""
    subpath = path_parts[2] if len(path_parts) > 2 else ""
    return owner, repo, subpath, tag


def _raw_url(owner: str, repo: str, tag: str, subpath: str) -> str:
    base = f"https://raw.githubusercontent.com/{owner}/{repo}/{tag}"
    if subpath:
        return f"{base}/{subpath}/action.yml"
    return f"{base}/action.yml"


class ActionFetchError(Exception):
    """Raised when an action.yml cannot be retrieved."""


def fetch_action_yml(ref: str) -> dict:
    """Fetch and parse an ``action.yml`` from GitHub.

    Tries the raw URL first, then a fallback with ``action.yaml``.
    """
    owner, repo, subpath, tag = _parse_ref(ref)
    urls = [
        _raw_url(owner, repo, tag, subpath),
        _raw_url(owner, repo, tag, subpath).replace("action.yml", "action.yaml"),
    ]
    for url in urls:
        try:
            resp = httpx.get(url, follow_redirects=True, timeout=15)
            if resp.status_code == 200:
                return load_yaml_string(resp.text)
        except httpx.HTTPError:
            continue
    raise ActionFetchError(
        f"Could not fetch action.yml for '{ref}'. Tried:\n"
        + "\n".join(f"  - {u}" for u in urls)
    )


def action_spec_from_ref(ref: str) -> ActionSpec:
    """Fetch action.yml from GitHub and return an :class:`ActionSpec`."""
    data = fetch_action_yml(ref)
    return parse_action_spec(ref, action_yml_data=data)


# ---------------------------------------------------------------------------
# Manual declaration from recipe
# ---------------------------------------------------------------------------


def action_spec_from_declaration(
    ref: str,
    *,
    inputs: dict[str, dict] | None = None,
    outputs: list[str] | None = None,
) -> ActionSpec:
    """Build an :class:`ActionSpec` from inline recipe declarations.

    Used when the recipe manually annotates inputs/outputs for a ``run:``
    step or overrides the fetched metadata.
    """
    parsed_inputs: dict[str, InputSpec] = {}
    for name, meta in (inputs or {}).items():
        norm = normalize_name(name)
        parsed_inputs[norm] = InputSpec(
            name=norm,
            required=_parse_bool(meta.get("required", False)),
            default=meta.get("default"),
            description=str(meta.get("description", "")),
        )

    parsed_outputs: dict[str, OutputSpec] = {}
    for name in outputs or []:
        norm = normalize_name(name)
        parsed_outputs[norm] = OutputSpec(name=norm)

    return ActionSpec(ref=ref, inputs=parsed_inputs, outputs=parsed_outputs)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def action_local_name(ref: str) -> str:
    """Extract the last path segment of an action ref, normalized.

    >>> action_local_name('i2mint/wads/actions/run-tests@master')
    'run_tests'
    >>> action_local_name('actions/checkout@v4')
    'checkout'
    """
    without_tag = ref.split("@", 1)[0]
    last_segment = without_tag.rsplit("/", 1)[-1]
    return normalize_name(last_segment)
