"""Characterization tests pinning the ``reci`` command-line grammar.

Recorded from the pre-migration ``argh`` implementation and replayed against
:mod:`cw`, so the CLI surface cannot drift silently. Three things are pinned that
nothing else in the suite would catch:

* the **no-argument** case — argh printed usage to *stdout* and exited **0**, where a
  plain argparse parser with a required subparser exits 2 to stderr;
* the **exit code**, which ``cw.dispatch`` *returns* rather than raising — so
  ``__main__`` must ``raise SystemExit(main())`` or every failure would report success;
* the flag spellings and defaults argparse infers from each command's signature.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import textwrap

import pytest

import cw
from reci.__main__ import COMMANDS, main

CYCLIC_RECIPE = textwrap.dedent(
    """\
    name: demo
    on:
      push:
    jobs:
      a:
        runs-on: ubuntu-latest
        needs: [b]
        steps:
          - run: echo hi
      b:
        runs-on: ubuntu-latest
        needs: [a]
        steps:
          - run: echo hi
    """
)


@pytest.fixture(scope="module")
def parser():
    """The very parser :func:`reci.__main__.main` dispatches, built without I/O."""
    return cw.mk_parser(COMMANDS, prog="reci")


def _run(*argv, cwd=None):
    """Run ``python -m reci ARGV`` end to end and return the completed process."""
    return subprocess.run(
        [sys.executable, "-m", "reci", *argv],
        capture_output=True,
        text=True,
        cwd=cwd,
        env={"COLUMNS": "80", **_clean_env()},
    )


def _clean_env():
    import os

    return {k: v for k, v in os.environ.items() if k != "COLUMNS"}


# --------------------------------------------------------------------------- grammar


def test_the_four_commands_are_the_ones_dispatched(parser):
    assert [f.__name__ for f in COMMANDS] == [
        "compile",
        "validate",
        "scaffold",
        "inspect",
    ]
    assert parser.format_usage() == (
        "usage: reci [-h] {compile,validate,scaffold,inspect} ...\n"
    )


@pytest.mark.parametrize(
    "command, usage",
    [
        (
            "compile",
            "usage: reci compile [-h] [--config-adapter CONFIG_ADAPTER]"
            " [--config-path CONFIG_PATH] [-o OUTPUT] recipe",
        ),
        (
            "validate",
            "usage: reci validate [-h] [-r RECIPE] [--config-adapter CONFIG_ADAPTER]"
            " [--config-path CONFIG_PATH] [-f FORMAT] [-m MAX_WARNINGS]",
        ),
        (
            "scaffold",
            "usage: reci scaffold [-h] [--config-adapter CONFIG_ADAPTER]"
            " [--config-path CONFIG_PATH] [-o OUTPUT] recipe",
        ),
        ("inspect", "usage: reci inspect [-h] action-ref"),
    ],
)
def test_each_subcommand_keeps_its_recorded_usage_line(parser, command, usage):
    """Flag spellings, short options and positionals, exactly as argh rendered them.

    Note what is *absent*: ``--config-adapter`` and ``--config-path`` get no short
    flag, because they collide on ``-c``. Line wrapping is normalised away, since it
    depends on the terminal width the test happens to run under.
    """
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    got = " ".join(subparsers.choices[command].format_usage().split())
    assert got == usage


def test_defaults_match_the_function_signatures(parser):
    namespace = parser.parse_args(["validate"])
    assert namespace.recipe == "recipe.yml"
    assert namespace.config_adapter == "pyproject"
    assert namespace.config_path is None
    assert namespace.format == "cli"
    assert namespace.max_warnings == -1


# ------------------------------------------------------------------------ exit codes


def test_no_arguments_prints_usage_to_stdout_and_exits_zero():
    """argh's behaviour, which bare argparse does not reproduce. Pinned deliberately."""
    done = _run()
    assert done.returncode == 0
    assert done.stdout.startswith("usage: ")
    assert done.stderr == ""


@pytest.mark.parametrize(
    "argv",
    [
        ("no-such-command",),
        ("inspect",),  # missing required positional
        ("compile",),  # missing required positional
        ("validate", "--no-such-flag"),
        ("validate", "--max-warnings", "notanint"),
    ],
)
def test_bad_invocations_exit_two(argv):
    done = _run(*argv)
    assert done.returncode == 2
    assert done.stdout == ""
    assert done.stderr.startswith("usage: ")


def test_a_validation_error_still_exits_one(tmp_path):
    """``validate`` calls ``sys.exit(1)``; ``cw.dispatch`` *returns* that code.

    This is the test that fails if ``__main__`` ever loses its
    ``raise SystemExit(main())`` — every other test here passes either way.
    """
    (tmp_path / "cycle.yml").write_text(CYCLIC_RECIPE)
    done = _run("validate", "--recipe", "cycle.yml", cwd=tmp_path)
    assert done.returncode == 1
    assert "DAG001" in done.stdout


def test_main_returns_the_exit_code_rather_than_swallowing_it(tmp_path, monkeypatch):
    """The in-process half of the same guarantee: ``main()`` yields an int, not None."""
    (tmp_path / "cycle.yml").write_text(CYCLIC_RECIPE)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["reci", "validate", "--recipe", "cycle.yml"])
    assert main() == 1
    monkeypatch.setattr(sys, "argv", ["reci", "no-such-command"])
    assert main() == 2
