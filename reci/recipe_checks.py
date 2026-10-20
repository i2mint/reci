"""Whole-recipe checks that need the recipe text and the config, not the step graph.

Shared by the compiler (which refuses to emit a workflow with these problems)
and the validation rules (which report them), so both always agree.
"""

from __future__ import annotations

import datetime
import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from ruamel.yaml.comments import TaggedScalar

from reci.recipe import Recipe
from reci.yaml_gen import scalar_source_text

#: The generated job that exports config values; recipe jobs may not use the id
#: when config is supplied.
SETUP_JOB_ID = "setup"

_STRING_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")  # GitHub strings: '...' with ''
# ``config.key`` as a whole reference: not a suffix of another path
# (``github.event.config.x``) or word (``myconfig.x``), and not a nested access
# (``config.x.y`` / ``config.x[0]``: outputs are strings, left for actionlint);
# keys may contain hyphens.
_CONFIG_NAME_RE = re.compile(r"(?<![\w.\-])config\.([A-Za-z_][\w\-]*)(?![\w\-]*[.\[])")


def _expression_spans(text: str) -> Iterator[tuple[int, int]]:
    """``(body_start, body_end)`` of each ``${{ body }}`` in *text*.

    A ``}}`` inside a single-quoted string literal does not end the expression.
    """
    pos = 0
    while (start := text.find("${{", pos)) != -1:
        i = start + 3
        while i < len(text):
            if text[i] == "'":
                literal = _STRING_LITERAL_RE.match(text, i)
                i = literal.end() if literal else i + 1
            elif text.startswith("}}", i):
                yield start + 3, i
                pos = i + 2
                break
            else:
                i += 1
        else:
            return  # unterminated: leave the rest alone


def _code_pieces(body: str) -> Iterator[tuple[int, str]]:
    """``(offset, code)`` for each stretch of *body* outside a string literal."""
    pos = 0
    for literal in _STRING_LITERAL_RE.finditer(body):
        yield pos, body[pos : literal.start()]
        pos = literal.end()
    yield pos, body[pos:]


# The ``config`` context as a whole word (not ``github.event.config`` / ``myconfig``).
_CONFIG_WORD_RE = re.compile(r"(?<![\w.\-])config(?![\w\-])")
_CONFIG_USE_RE = re.compile(r"config(?:\.[\w\-*]+|\[)*")


def unsupported_config_refs(text: str) -> list[str]:
    """The uses of the ``config`` context in *text* that reci cannot rewrite.

    Only ``config.<key>`` maps to a setup-job output.  Nested access
    (``config.x.y``), bracket access (``config['x']``) and the whole context
    (``toJSON(config)``, ``config.*``) have no counterpart, and would reach
    GitHub unrewritten, where ``config`` is no context.

    >>> unsupported_config_refs("${{ config.a }} ${{ config.b.c }} ${{ config['d'] }}")
    ['config.b.c', 'config[']
    >>> unsupported_config_refs("${{ toJSON(config) }} ${{ 'config' }} ${{ config.a }}")
    ['config']
    """
    found: list[str] = []
    for body_start, body_end in _expression_spans(text):
        body = text[body_start:body_end]
        for offset, code in _code_pieces(body):
            for word in _CONFIG_WORD_RE.finditer(code):
                if not _CONFIG_NAME_RE.match(code, word.start()):
                    found.append(_CONFIG_USE_RE.match(code, word.start()).group())
    return found


# ``steps`` / ``needs`` and a path of ``.name`` / ``['name']`` accesses, then an open
# ``[``: the text before a quoted index that can name a step or a job.  A literal indexing
# anything else (``fromJSON(env.M)['steps.p.outputs.v']``) is just data.
_CONTEXT_INDEX_RE = re.compile(
    r"(?<![\w.\-])(?:steps|needs)(?:\s*\.\s*[\w\-]+|\s*\[\s*'(?:[^']|'')*'\s*\])*\s*\[\s*$",
    re.IGNORECASE,
)


def expression_texts(text: str) -> Iterator[str]:
    """The body of each ``${{ }}`` in *text*, string literals blanked.

    A literal survives only as the index of a bracket access on the ``steps`` or
    ``needs`` context (``steps['p']``), so a name inside a message or comparison
    (``'steps.p.outputs.v'``), or indexing something else, is never taken for a reference.

    >>> list(expression_texts("${{ steps['p'].outputs.v == 'steps.q.outputs.w' }} x"))
    [" steps['p'].outputs.v == '' "]
    >>> list(expression_texts("${{ fromJSON(env.M)['steps.p.outputs.v'] }}"))
    [" fromJSON(env.M)[''] "]
    """
    for start, end in _expression_spans(text):
        body = text[start:end]
        pieces, pos = [], 0
        for literal in _STRING_LITERAL_RE.finditer(body):
            before = body[pos : literal.start()]
            indexed = (
                _CONTEXT_INDEX_RE.search(body[: literal.start()]) is not None
                and body[literal.end() :].lstrip().startswith("]")
            )
            pieces += [before, literal.group() if indexed else "''"]
            pos = literal.end()
        pieces.append(body[pos:])
        yield "".join(pieces)


def outside_expressions(text: str) -> str:
    """*text* with every ``${{ }}`` expression removed.

    >>> outside_expressions("config.flag && ${{ x }}").strip()
    'config.flag &&'
    """
    pieces, last = [], 0
    for start, end in _expression_spans(text):
        pieces.append(text[last : start - 3])
        last = end + 2
    pieces.append(text[last:])
    return " ".join(pieces)


def as_expression(text: str) -> str:
    """An ``if:`` value as a ``${{ }}`` expression: GitHub evaluates it either way.

    >>> as_expression("config.flag"), as_expression("${{ config.flag }}")
    ('${{ config.flag }}', '${{ config.flag }}')
    """
    return text if "${{" in text else "${{ " + text + " }}"


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

    def rewrite_code(body: str) -> str:
        pieces, pos = [], 0
        for literal in _STRING_LITERAL_RE.finditer(body):
            pieces.append(_CONFIG_NAME_RE.sub(repl, body[pos : literal.start()]))
            pieces.append(literal.group())
            pos = literal.end()
        pieces.append(_CONFIG_NAME_RE.sub(repl, body[pos:]))
        return "".join(pieces)

    out, last = [], 0
    for body_start, body_end in _expression_spans(text):
        body = text[body_start:body_end]
        new_body = rewrite_code(body)
        if new_body != body:
            out.append(text[last : body_start - 3])
            out.append("${{ " + new_body.strip() + " }}")
            last = body_end + 2
    out.append(text[last:])
    return "".join(out)


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


# A GitHub job-output id: letters, digits, ``_`` and ``-``, not starting with a digit.
_OUTPUT_ID_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]*")
# What the setup job can carry verbatim in a YAML ``run:`` block and a
# GITHUB_OUTPUT file: tab and newline plus everything printable.  CR, NEL, the
# Unicode line/paragraph separators, NUL and other C0 controls are YAML line
# breaks or invalid, so they would be altered or break the file.
_UNEXPORTABLE_CHAR_RE = re.compile(
    "[\x00-\x08\x0b-\x1f\x7f\x80-\x9f\u2028\u2029\ud800-\udfff\ufeff\ufffe\uffff]"
)


#: A decimal number as written, ``3.10`` (GitHub would read the number as 3.1).
_DECIMAL_SPELLING_RE = re.compile(r"-?\d+\.\d+")


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime.date, datetime.time)):  # also datetime.datetime
        return value.isoformat()
    if isinstance(value, TaggedScalar):  # `!!str 3.10`, or another tag
        return value.value
    unwrap = getattr(value, "unwrap", None)  # tomlkit items (Bool...) -> Python
    if unwrap is not None:
        return unwrap()
    raise TypeError(f"{type(value).__name__} has no JSON form")


def serialize_config_value(value: Any) -> str:
    """A config value as the text of a ``$GITHUB_OUTPUT`` entry.

    Lists, mappings and tuples become JSON (dates inside them as ISO text); a
    boolean ``true`` / ``false``; a number as the author wrote it (a TOML or
    YAML ``3.10`` stays ``3.10``, not ``3.1``).  ``None``, bytes and other
    objects have no faithful text and raise :class:`TypeError`.

    >>> serialize_config_value({"d": datetime.date(2024, 1, 2), "t": (1, 2)})
    '{"d": "2024-01-02", "t": [1, 2]}'
    >>> serialize_config_value(datetime.datetime(2024, 1, 2, 3, 4, 5))
    '2024-01-02T03:04:05'
    >>> serialize_config_value(True), serialize_config_value(7)
    ('true', '7')
    >>> serialize_config_value(None)
    Traceback (most recent call last):
    ...
    TypeError: None (null) has no text form; give the key a value or remove it
    """
    if isinstance(value, TaggedScalar):
        value = value.value
    elif not isinstance(value, (str, int, float, list, dict)) and hasattr(
        value, "unwrap"
    ):
        value = value.unwrap()  # a tomlkit Bool (numbers keep their spelling below)
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, default=_json_default)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        raise TypeError(
            "None (null) has no text form; give the key a value or remove it"
        )
    if isinstance(value, (bytes, bytearray)):
        raise TypeError("bytes have no text form")
    if isinstance(value, float):
        # Keep a decimal spelling (3.10); hex, underscores, exponents, ``.5``,
        # inf/nan are normalised by str(), as before
        as_string = getattr(value, "as_string", None)  # tomlkit keeps the spelling
        text = as_string() if as_string else scalar_source_text(value)
        return text if _DECIMAL_SPELLING_RE.fullmatch(text) else str(value)
    if isinstance(value, int):
        return str(int(value))
    if isinstance(value, (datetime.date, datetime.time)):  # also datetime.datetime
        return value.isoformat()  # same ISO text as inside a list or mapping
    if isinstance(value, str):
        return str(value)
    raise TypeError(f"{type(value).__name__} has no text form")


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


def _if_expression(text: str | None) -> str | None:
    return None if text is None else as_expression(text)


def _recipe_strings(recipe: Recipe) -> Iterator[tuple[str, str, bool]]:
    """``(location, text, needs_context_available)`` for each string that may hold
    a config reference.

    Config values reach a workflow through ``needs.setup.outputs``, and GitHub
    does not offer the ``needs`` context in workflow-level ``env`` or in job
    ``permissions``.
    """
    workflow_fields = {
        "name": recipe.name,
        "on": recipe.on,
        "defaults": recipe.defaults,
        **recipe.extra,
    }
    for text in _walk_strings(recipe.env):
        yield "workflow env", text, False
    for key, value in workflow_fields.items():
        for text in _walk_strings(value):
            yield f"workflow {key}", text, False
    for job_id, job in recipe.jobs.items():
        for text in _walk_strings(job.permissions):
            yield f"{job_id} permissions", text, False
        job_fields = (
            _if_expression(job.if_),
            job.runs_on,
            job.strategy,
            job.env,
            job.continue_on_error,  # a bool contributes no strings
            job.extra,
        )
        for text in _walk_strings(list(job_fields)):
            yield job_id, text, True
        for step in job.steps:
            step_fields = (
                step.name,
                step.run,
                _if_expression(step.if_),
                step.with_,
                step.env,
                step.continue_on_error,
                step.extra,
            )
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


def _conditions(recipe: Recipe) -> Iterator[tuple[str, str]]:
    """``(location, text)`` for each ``if:`` of the recipe's jobs and steps."""
    for job_id, job in recipe.jobs.items():
        if job.if_:
            yield job_id, job.if_
        for step in job.steps:
            if step.if_:
                yield f"{job_id}.{step.id}", step.if_


def bool_config_conditions(
    recipe: Recipe, config: dict[str, Any] | None
) -> list[tuple[str, str]]:
    """``(location, key)`` for each ``if:`` that is just a boolean config value.

    Config values reach the workflow as *strings*, so ``if: config.flag`` is true for
    ``'false'`` too; compare it: ``config.flag == 'true'``.
    """
    found = []
    for location, text in _conditions(recipe):
        body = text.strip()
        if body.startswith("${{") and body.endswith("}}"):
            body = body[3:-2].strip()
        match = re.fullmatch(r"!?\s*config\.([\w\-]+)", body)
        if match and isinstance((config or {}).get(match.group(1)), bool):
            found.append((location, match.group(1)))
    return found


def find_recipe_problems(
    recipe: Recipe, config: dict[str, Any] | None
) -> list[RecipeProblem]:
    """Problems that would make the compiled workflow invalid.

    * ``CONF004`` — ``${{ config.X }}`` where ``X`` is not a config key (the
      rewritten ``needs.setup.outputs.X`` would be empty or the setup job absent),
      or that sits where the ``needs`` context is unavailable.
    * ``DAG006`` — ``needs:`` naming a job that does not exist (``setup`` exists
      only when config is supplied).
    * ``CONF005`` — a config key that is not a valid output id, or a string value
      holding characters the setup job cannot export unchanged.
    * ``DAG007`` — a recipe job named ``setup`` while config is supplied: it
      would replace the generated setup job.
    """
    config = config or {}
    problems: list[RecipeProblem] = []

    config_keys = {k.casefold() for k in config if isinstance(k, str)}  # ids: no case
    unsupported: set[tuple[str, str]] = set()
    for location, text, _ in _recipe_strings(recipe):
        for ref in unsupported_config_refs(text):
            if (location, ref) not in unsupported:
                unsupported.add((location, ref))
                problems.append(
                    RecipeProblem(
                        "CONF004",
                        f"'{location}' uses '{ref}', which reci cannot rewrite: "
                        f"only 'config.<key>' is supported (config values are "
                        f"strings; parse a structured one with fromJSON in a "
                        f"step instead).",
                        location,
                    )
                )

    for location, name, needs_ok in config_references(recipe):
        if not needs_ok:
            message = (
                f"'{location}' references config.{name}, but GitHub offers no "
                f"'needs' context there; use a literal value."
            )
        elif name.casefold() not in config_keys:
            message = (
                f"'{location}' references config.{name}, which is not a config key."
            )
        else:
            continue
        problems.append(RecipeProblem("CONF004", message, location))

    for location, condition in _conditions(recipe):
        if "${{" in condition:
            for ref in _CONFIG_NAME_RE.finditer(outside_expressions(condition)):
                problems.append(
                    RecipeProblem(
                        "CONF004",
                        f"'{location}' has an if: that mixes plain text with "
                        f"'${{{{ }}}}' and uses {ref.group()} outside the expression, "
                        f"where reci cannot rewrite it; put the whole condition "
                        f"inside '${{{{ }}}}'.",
                        location,
                    )
                )
                break

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

    seen_keys: dict[str, str] = {}
    for key, value in config.items():
        if not isinstance(key, str) or not _OUTPUT_ID_RE.fullmatch(key):
            problems.append(
                RecipeProblem(
                    "CONF005",
                    f"Config key {key!r} is not a valid job-output id (a string of "
                    f"letters, digits, '_' and '-'; not starting with a digit), so "
                    f"the setup job cannot export it.",
                    "config",
                )
            )
        elif key.casefold() in seen_keys:
            problems.append(
                RecipeProblem(
                    "CONF005",
                    f"Config keys '{seen_keys[key.casefold()]}' and '{key}' differ "
                    f"only in case; job outputs are case-insensitive.",
                    "config",
                )
            )
        else:
            seen_keys[key.casefold()] = key
        try:
            exported = serialize_config_value(value)
        except TypeError as e:
            problems.append(
                RecipeProblem(
                    "CONF005",
                    f"The value of config key '{key}' ({type(value).__name__}) "
                    f"cannot be exported through $GITHUB_OUTPUT: {e}",
                    "config",
                )
            )
            continue
        if isinstance(value, (dict, list, tuple)):
            continue  # exported as JSON, which escapes control characters
        bad = _UNEXPORTABLE_CHAR_RE.search(exported)
        if bad:
            problems.append(
                RecipeProblem(
                    "CONF005",
                    f"The value of config key '{key}' contains the character "
                    f"{bad.group()!r}, which cannot be exported through "
                    f"$GITHUB_OUTPUT unchanged.",
                    "config",
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
