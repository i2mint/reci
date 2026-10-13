"""Whole-recipe checks that need the recipe text and the config, not the step graph.

Shared by the compiler (which refuses to emit a workflow with these problems)
and the validation rules (which report them), so both always agree.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from reci.recipe import Recipe

#: The generated job that exports config values; recipe jobs may not use the id
#: when config is supplied.
SETUP_JOB_ID = "setup"

_EXPRESSION_RE = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
_STRING_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")  # GitHub strings: '...' with ''
# ``config.key`` as a whole reference: not a suffix of another path
# (``github.event.config.x``) or word (``myconfig.x``); keys may contain hyphens.
_CONFIG_NAME_RE = re.compile(r"(?<![\w.\-])config\.([A-Za-z_][\w\-]*)")


def sub_config_refs(text: str, repl: Callable[[re.Match], str]) -> str:
    """Substitute every ``config.<key>`` inside a ``${{ ... }}`` in *text*.

    *repl* receives the match (``group(1)`` is the key).  Only expression code is
    touched, never string literals inside an expression (``'config.json'``) and
    never text outside ``${{ }}`` (``cat config.json``).  An expression that
    changes is re-emitted as ``${{ <code> }}``; the others are left verbatim.

    >>> sub_config_refs("${{ fromJson(config.v) }} cat config.json",
    ...                 lambda m: "NEEDS." + m.group(1))
    '${{ fromJson(NEEDS.v) }} cat config.json'
    """

    def in_expression(match: re.Match) -> str:
        body, pieces, pos = match.group(1), [], 0
        for literal in _STRING_LITERAL_RE.finditer(body):
            pieces.append(_CONFIG_NAME_RE.sub(repl, body[pos : literal.start()]))
            pieces.append(literal.group())
            pos = literal.end()
        pieces.append(_CONFIG_NAME_RE.sub(repl, body[pos:]))
        new_body = "".join(pieces)
        return match.group(0) if new_body == body else "${{ " + new_body.strip() + " }}"

    return _EXPRESSION_RE.sub(in_expression, text)


def config_names(text: str) -> list[str]:
    """The config keys referenced in *text*'s ``${{ ... }}`` expressions, in order.

    >>> config_names("${{ config.a }} ${{ !config.b && 'config.c' }} config.d")
    ['a', 'b']
    """
    names: list[str] = []

    def collect(match: re.Match) -> str:
        names.append(match.group(1))
        return match.group(0)

    sub_config_refs(text, collect)
    return names


@dataclass(frozen=True)
class RecipeProblem:
    """One problem found by :func:`find_recipe_problems`."""

    rule_id: str  # the validation rule that reports it
    message: str
    location: str | None = None


def _walk_strings(obj: Any) -> Iterator[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)


def _recipe_strings(recipe: Recipe) -> Iterator[tuple[str, str, bool]]:
    """``(location, text, needs_context_available)`` for each string that may hold
    a config reference.

    Config values reach a workflow through ``needs.setup.outputs``, and GitHub
    does not offer the ``needs`` context in workflow-level ``env`` or in job
    ``permissions``.
    """
    for text in _walk_strings(recipe.env):
        yield "workflow env", text, False
    for job_id, job in recipe.jobs.items():
        for text in _walk_strings(job.permissions):
            yield f"{job_id} permissions", text, False
        job_fields = (job.if_, job.runs_on, job.strategy, job.env)
        for text in _walk_strings(list(job_fields)):
            yield job_id, text, True
        for step in job.steps:
            step_fields = (step.name, step.run, step.if_, step.with_, step.env)
            for text in _walk_strings(list(step_fields)):
                yield f"{job_id}.{step.id}", text, True


def config_references(recipe: Recipe) -> list[tuple[str, str, bool]]:
    """``(location, key, needs_context_available)`` for each ``${{ config.key }}``.

    Duplicates within one location are reported once.
    """
    seen: set[tuple[str, str]] = set()
    refs: list[tuple[str, str, bool]] = []
    for location, text, needs_ok in _recipe_strings(recipe):
        for name in config_names(text):
            if (location, name) not in seen:
                seen.add((location, name))
                refs.append((location, name, needs_ok))
    return refs


def find_recipe_problems(
    recipe: Recipe, config: dict[str, Any] | None
) -> list[RecipeProblem]:
    """Problems that would make the compiled workflow invalid.

    * ``CONF004`` — ``${{ config.X }}`` where ``X`` is not a config key (the
      rewritten ``needs.setup.outputs.X`` would be empty or the setup job absent),
      or that sits where the ``needs`` context is unavailable.
    * ``DAG006`` — ``needs:`` naming a job that does not exist (``setup`` exists
      only when config is supplied).
    * ``DAG007`` — a recipe job named ``setup`` while config is supplied: it
      would replace the generated setup job.
    """
    config = config or {}
    problems: list[RecipeProblem] = []

    for location, name, needs_ok in config_references(recipe):
        if not needs_ok:
            message = (
                f"'{location}' references config.{name}, but GitHub offers no "
                f"'needs' context there; use a literal value."
            )
        elif name not in config:
            message = (
                f"'{location}' references config.{name}, which is not a config key."
            )
        else:
            continue
        problems.append(RecipeProblem("CONF004", message, location))

    known = set(recipe.jobs) | ({SETUP_JOB_ID} if config else set())
    for job_id, job in recipe.jobs.items():
        for needed in job.needs:
            if needed not in known:
                problems.append(
                    RecipeProblem(
                        "DAG006",
                        f"Job '{job_id}' needs '{needed}', which is not a job"
                        + (
                            " (the setup job exists only when config is supplied)."
                            if needed == SETUP_JOB_ID
                            else "."
                        ),
                        job_id,
                    )
                )

    if config and SETUP_JOB_ID in recipe.jobs:
        problems.append(
            RecipeProblem(
                "DAG007",
                f"A recipe job named '{SETUP_JOB_ID}' would replace the generated "
                f"setup job that exports the config; rename it.",
                SETUP_JOB_ID,
            )
        )
    return problems
