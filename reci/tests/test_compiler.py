"""Compiler: golden workflows, five-level input wiring, cross-job forwarding.

The goldens are the point of this file: ``reci`` emits CI that gates other
repos' publishing, so a change that quietly alters the emitted YAML must show up
as a failing diff here. Update a golden only when the change is intended.
"""

import os
import shutil
import sys

import pytest

from reci.compiler import _rewrite_config_refs, compile_recipe
from reci.recipe import parse_recipe_string
from reci.yaml_gen import dump_workflow, load_yaml_string

from reci.tests._helpers import assert_valid_workflow, mk_spec


def _compile(recipe_yaml, specs, config=None, *, lint=True):
    """Compile, and require the result to pass actionlint (skipped if absent)."""
    wf = compile_recipe(parse_recipe_string(recipe_yaml), specs, config=config)
    if lint:
        assert_valid_workflow(wf)
    return wf


GOLDEN_PIPELINE = """\
name: CI
on:
  push:
    branches:
      - main
jobs:
  setup:
    name: Setup
    runs-on: ubuntu-latest
    outputs:
      python_version: '${{ steps.config.outputs.python_version }}'
      acme_ci_extra: '${{ steps.config.outputs.acme_ci_extra }}'
    steps:
      - name: Export config
        id: config
        run: |-
          {
            printf '%s=%s\\n' python_version 3.12
            printf '%s=%s\\n' acme_ci_extra 'a b'
          } >> "$GITHUB_OUTPUT"
  test:
    runs-on: ubuntu-latest
    needs:
      - setup
    steps:
      - id: checkout
        uses: actions/checkout@v4
      - id: build
        uses: acme/ci/actions/build@v1
        with:
          python_version: '${{ needs.setup.outputs.python_version }}'
      - id: run_tests
        uses: acme/ci/actions/run-tests@v1
        with:
          wheel_path: '${{ steps.build.outputs.wheel_path }}'
          verbose: 'true'
"""


def test_golden_pipeline(pipeline_recipe_yaml, pipeline_specs):
    wf = _compile(
        pipeline_recipe_yaml,
        pipeline_specs,
        config={"python_version": "3.12", "acme_ci_extra": "a b"},
    )
    assert dump_workflow(wf) == GOLDEN_PIPELINE


def test_golden_is_deterministic_and_pure(pipeline_recipe_yaml, pipeline_specs):
    recipe = parse_recipe_string(pipeline_recipe_yaml)
    cfg = {"python_version": "3.12"}
    first = dump_workflow(compile_recipe(recipe, pipeline_specs, config=cfg))
    second = dump_workflow(compile_recipe(recipe, pipeline_specs, config=cfg))
    assert first == second
    assert cfg == {"python_version": "3.12"}  # inputs not mutated


# -- five-level precedence ---------------------------------------------------

_ONE_STEP = "on: push\njobs:\n  j:\n    steps:\n      - id: up\n        uses: x/up@v1\n      - id: s\n        uses: x/s@v1{extra}\n"


def _step_with(config, *, extra="", s_inputs=None, up_outputs=("v",)):
    specs = {
        "x/up@v1": mk_spec("x/up@v1", outputs=list(up_outputs)),
        "x/s@v1": mk_spec("x/s@v1", inputs=s_inputs or {"v": {"required": True}}),
    }
    wf = _compile(_ONE_STEP.format(extra=extra), specs, config=config)
    return wf["jobs"]["j"]["steps"][1].get("with", {})


def test_explicit_with_beats_upstream_and_config():
    w = _step_with({"v": "cfg"}, extra="\n        with: {v: explicit}")
    assert w == {"v": "explicit"}


def test_upstream_output_beats_config():
    assert _step_with({"v": "cfg"}) == {"v": "${{ steps.up.outputs.v }}"}


def test_config_beats_action_default():
    w = _step_with({"v": "cfg"}, s_inputs={"v": {"default": "d"}}, up_outputs=())
    assert w == {"v": "${{ needs.setup.outputs.v }}"}


def test_scoped_config_key_beats_shared_key():
    w = _step_with({"v": "shared", "s__v": "scoped"}, up_outputs=())
    assert w == {"v": "${{ needs.setup.outputs.s__v }}"}


def test_scoped_key_only_applies_to_its_action():
    w = _step_with(
        {"other__v": "nope"}, s_inputs={"v": {"default": "d"}}, up_outputs=()
    )
    assert w == {}  # falls through to the action default: input omitted


def test_default_means_input_is_omitted_and_required_unsourced_is_left_unwired():
    assert _step_with({}, s_inputs={"v": {"default": "d"}}, up_outputs=()) == {}
    assert _step_with({}, s_inputs={"v": {"required": True}}, up_outputs=()) == {}


def test_bind_renames_the_upstream_output_searched():
    specs = {
        "x/up@v1": mk_spec("x/up@v1", outputs=["artifact"]),
        "x/s@v1": mk_spec("x/s@v1", inputs={"path": {"required": True}}),
    }
    recipe = _ONE_STEP.format(extra="\n        bind: {path: artifact}")
    w = _compile(recipe, specs)["jobs"]["j"]["steps"][1]["with"]
    assert w == {"path": "${{ steps.up.outputs.artifact }}"}


def test_nearest_upstream_producer_wins():
    specs = {
        "x/p@v1": mk_spec("x/p@v1", outputs=["v"]),
        "x/s@v1": mk_spec("x/s@v1", inputs={"v": {"required": True}}),
    }
    recipe = (
        "on: push\njobs:\n  j:\n    steps:\n      - {id: first, uses: x/p@v1}\n"
        "      - {id: second, uses: x/p@v1}\n      - {id: s, uses: x/s@v1}\n"
    )
    w = _compile(recipe, specs)["jobs"]["j"]["steps"][2]["with"]
    assert w == {"v": "${{ steps.second.outputs.v }}"}


def test_declared_run_step_outputs_feed_downstream_inputs():
    specs = {"x/s@v1": mk_spec("x/s@v1", inputs={"tag": {"required": True}})}
    recipe = (
        "on: push\njobs:\n  j:\n    steps:\n      - {id: mk, run: echo, outputs: [tag]}\n"
        "      - {id: s, uses: x/s@v1}\n"
    )
    w = _compile(recipe, specs)["jobs"]["j"]["steps"][1]["with"]
    assert w == {"tag": "${{ steps.mk.outputs.tag }}"}


# -- config references and the setup job --------------------------------------


def test_config_refs_are_rewritten_everywhere():
    recipe = """\
on: push
jobs:
  j:
    if: ${{ config.gate }}
    env: {E: "${{ config.e }}"}
    strategy:
      matrix:
        py: ${{ fromJson(config.versions) }}
    steps:
      - run: echo ${{ config.cmd }}
        if: ${{ config.s_if }}
        env: {K: "${{ config.k }}"}
      - uses: x/s@v1
        with: {a: "${{ config.a }}"}
"""
    config = dict.fromkeys(["gate", "e", "versions", "cmd", "s_if", "k", "a"], "v")
    # lint=False: config.X inside fromJson(...) is not rewritten yet (#19)
    wf = _compile(recipe, {"x/s@v1": mk_spec("x/s@v1")}, config=config, lint=False)
    j = wf["jobs"]["j"]
    n = "needs.setup.outputs"
    assert j["if"] == f"${{{{ {n}.gate }}}}"
    assert j["env"] == {"E": f"${{{{ {n}.e }}}}"}
    assert j["steps"][0]["run"] == f"echo ${{{{ {n}.cmd }}}}"
    assert j["steps"][0]["if"] == f"${{{{ {n}.s_if }}}}"
    assert j["steps"][0]["env"] == {"K": f"${{{{ {n}.k }}}}"}
    assert j["steps"][1]["with"] == {"a": f"${{{{ {n}.a }}}}"}


def test_rewrite_config_refs_tolerates_whitespace_and_leaves_other_contexts():
    assert _rewrite_config_refs("${{config.x}} ${{ github.sha }}") == (
        "${{ needs.setup.outputs.x }} ${{ github.sha }}"
    )


def test_setup_job_declares_one_output_per_config_key():
    wf = _compile(
        "on: push\njobs:\n  j:\n    steps:\n      - run: echo\n",
        {},
        config={"flag": True, "off": False, "n": 3, "s": "a b"},
    )
    setup = wf["jobs"]["setup"]
    assert list(setup["outputs"]) == ["flag", "off", "n", "s"]
    assert setup["outputs"]["n"] == "${{ steps.config.outputs.n }}"
    assert setup["steps"][0]["id"] == "config"  # the id the outputs refer to


needs_posix_bash = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="the setup script targets a POSIX bash (ubuntu runner)",
)


def _run_setup_script(tmp_path, config):
    import subprocess

    wf = _compile(
        "on: push\njobs:\n  j:\n    steps:\n      - run: echo\n", {}, config=config
    )
    # through the YAML text, as the runner would read it
    wf = load_yaml_string(dump_workflow(wf))
    out = tmp_path / "gh_output"
    out.write_text("")
    subprocess.run(
        ["bash", "-c", wf["jobs"]["setup"]["steps"][0]["run"]],
        env={**os.environ, "GITHUB_OUTPUT": str(out)},
        check=True,
    )
    return _parse_github_output(out.read_text())


def _parse_github_output(text):
    """Parse a GITHUB_OUTPUT file as the Actions runner does (k=v and k<<DELIM)."""
    result, lines = {}, iter(text.split("\n"))
    for line in lines:
        if "<<" in line.split("=", 1)[0]:
            key, delimiter = line.split("<<", 1)
            body = []
            for body_line in lines:
                if body_line == delimiter:
                    break
                body.append(body_line)
            result[key] = "\n".join(body)
        elif "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


@needs_posix_bash
def test_setup_script_exports_scalars_through_a_real_shell(tmp_path):
    got = _run_setup_script(tmp_path, {"flag": True, "off": False, "n": 3, "s": "a b"})
    assert got == {"flag": "true", "off": "false", "n": "3", "s": "a b"}


@needs_posix_bash
def test_setup_script_does_not_expand_shell_syntax_in_values(tmp_path):
    got = _run_setup_script(tmp_path, {"s": "cost $5 `echo X`"})
    assert got == {"s": "cost $5 `echo X`"}


@needs_posix_bash
def test_setup_script_exports_lists_and_dicts_as_valid_json(tmp_path):
    import json

    got = _run_setup_script(tmp_path, {"lst": ["3.10", "3.12"], "d": {"a": "b"}})
    assert json.loads(got["lst"]) == ["3.10", "3.12"]
    assert json.loads(got["d"]) == {"a": "b"}


def test_job_passthrough_fields_and_setup_need_first():
    recipe = """\
name: P
on: push
jobs:
  a:
    steps: [{run: echo}]
  b:
    needs: [a]
    runs-on: macos-latest
    continue-on-error: true
    permissions: {contents: read}
    strategy: {matrix: {os: [x]}}
    steps: [{run: echo}]
"""
    wf = _compile(recipe, {}, config={"k": "v"})
    b = wf["jobs"]["b"]
    assert b["needs"] == ["setup", "a"]
    assert b["runs-on"] == "macos-latest" and b["continue-on-error"] is True
    assert b["permissions"] == {"contents": "read"}
    assert b["strategy"] == {"matrix": {"os": ["x"]}}
    assert wf["name"] == "P"


def test_unnamed_recipe_gets_default_name():
    wf = _compile("on: push\njobs:\n  j:\n    steps: [{run: echo}]\n", {})
    assert wf["name"] == "CI"


# -- known defects, pinned so the fix flips them ------------------------------


def test_no_config_means_no_dangling_needs_setup():
    wf = _compile("on: push\njobs:\n  j:\n    steps: [{run: echo}]\n", {})
    assert "setup" not in wf["jobs"]
    assert "needs" not in wf["jobs"]["j"]  # not even an empty list


def test_cross_job_input_is_wired_through_needs_outputs():
    specs = {
        "x/a@v1": mk_spec("x/a@v1", outputs=["wheel_path"]),
        "x/b@v1": mk_spec("x/b@v1", inputs={"wheel_path": {"required": True}}),
    }
    recipe = (
        "on: push\njobs:\n  build:\n    steps: [{id: bld, uses: x/a@v1}]\n"
        "  test:\n    needs: build\n    steps: [{id: t, uses: x/b@v1}]\n"
    )
    wf = _compile(recipe, specs, config={"k": "v"})
    assert wf["jobs"]["test"]["steps"][0]["with"] == {
        "wheel_path": "${{ needs.build.outputs.wheel_path }}"
    }


def test_cross_job_wiring_honours_bind_and_prefers_same_job_producer():
    specs = {
        "x/a@v1": mk_spec("x/a@v1", outputs=["artifact", "v"]),
        "x/b@v1": mk_spec(
            "x/b@v1", inputs={"path": {"required": True}, "v": {"required": True}}
        ),
    }
    recipe = (
        "on: push\njobs:\n  build:\n    steps: [{id: bld, uses: x/a@v1}]\n"
        "  test:\n    steps:\n      - {id: loc, uses: x/a@v1}\n"
        "      - {id: t, uses: x/b@v1, bind: {path: artifact}}\n"
    )
    wf = _compile(recipe, specs)
    # ``path`` is bound to ``artifact``, which the same job already produces
    # (loc); the build job is not needed at all.
    assert wf["jobs"]["test"]["steps"][1]["with"] == {
        "path": "${{ steps.loc.outputs.artifact }}",
        "v": "${{ steps.loc.outputs.v }}",
    }
    assert "needs" not in wf["jobs"]["test"]


def test_cross_job_edge_applies_only_to_the_step_that_needs_it():
    specs = {
        "x/a@v1": mk_spec("x/a@v1", outputs=["v"]),
        "x/b@v1": mk_spec("x/b@v1", inputs={"v": {"required": True}}),
    }
    recipe = (
        "on: push\njobs:\n  p:\n    steps: [{id: prod, uses: x/a@v1}]\n"
        "  c:\n    steps:\n      - {id: t, uses: x/b@v1}\n"
        "      - {id: s, uses: x/a@v1}\n      - {id: u, uses: x/b@v1}\n"
    )
    steps = _compile(recipe, specs)["jobs"]["c"]["steps"]
    assert steps[0]["with"] == {"v": "${{ needs.p.outputs.v }}"}  # nothing earlier
    assert steps[2]["with"] == {"v": "${{ steps.s.outputs.v }}"}  # same job wins


def test_cross_job_wiring_honours_bind():
    specs = {
        "x/a@v1": mk_spec("x/a@v1", outputs=["artifact"]),
        "x/b@v1": mk_spec("x/b@v1", inputs={"path": {"required": True}}),
    }
    recipe = (
        "on: push\njobs:\n  build:\n    steps: [{id: bld, uses: x/a@v1}]\n"
        "  test:\n    steps: [{id: t, uses: x/b@v1, bind: {path: artifact}}]\n"
    )
    wf = _compile(recipe, specs)
    assert wf["jobs"]["test"]["needs"] == ["build"]
    assert wf["jobs"]["test"]["steps"][0]["with"] == {
        "path": "${{ needs.build.outputs.artifact }}"
    }


def test_cross_job_forwarding_adds_needs_and_job_outputs():
    """The parts of cross-job wiring that do work today (the expression: see the test above)."""
    specs = {
        "x/a@v1": mk_spec("x/a@v1", outputs=["wheel_path"]),
        "x/b@v1": mk_spec("x/b@v1", inputs={"wheel_path": {"required": True}}),
    }
    recipe = (
        "on: push\njobs:\n  build:\n    steps: [{id: bld, uses: x/a@v1}]\n"
        "  test:\n    steps: [{id: t, uses: x/b@v1}]\n"
    )
    wf = _compile(recipe, specs, config={"k": "v"})
    assert wf["jobs"]["build"]["outputs"] == {
        "wheel_path": "${{ steps.bld.outputs.wheel_path }}"
    }
    assert wf["jobs"]["test"]["needs"] == ["setup", "build"]  # inferred edge


def test_hyphenated_action_input_keeps_its_spelling():
    specs = {"x/s@v1": mk_spec("x/s@v1", inputs={"root-dir": {"required": True}})}
    wf = _compile(
        "on: push\njobs:\n  j:\n    steps: [{id: s, uses: x/s@v1}]\n",
        specs,
        config={"root_dir": "."},
    )
    assert "root-dir" in wf["jobs"]["j"]["steps"][0]["with"]


def test_hyphenated_step_output_keeps_its_spelling():
    specs = {
        "x/p@v1": mk_spec("x/p@v1", outputs=["wheel-path"]),
        "x/s@v1": mk_spec("x/s@v1", inputs={"wheel-path": {"required": True}}),
    }
    wf = _compile(
        "on: push\njobs:\n  j:\n    steps: [{id: p, uses: x/p@v1}, {id: s, uses: x/s@v1}]\n",
        specs,
    )
    assert wf["jobs"]["j"]["steps"][1]["with"] == {
        "wheel-path": "${{ steps.p.outputs.wheel-path }}"
    }

def test_hyphenated_output_keeps_its_spelling_across_jobs():
    specs = {
        "x/p@v1": mk_spec("x/p@v1", outputs=["wheel-path"]),
        "x/s@v1": mk_spec("x/s@v1", inputs={"wheel-path": {"required": True}}),
    }
    recipe = (
        "on: push\njobs:\n  build:\n    steps: [{id: p, uses: x/p@v1}]\n"
        "  test:\n    steps: [{id: s, uses: x/s@v1}]\n"
    )
    wf = _compile(recipe, specs)
    assert wf["jobs"]["build"]["outputs"] == {
        "wheel-path": "${{ steps.p.outputs.wheel-path }}"
    }
    assert wf["jobs"]["test"]["steps"][0]["with"] == {
        "wheel-path": "${{ needs.build.outputs.wheel-path }}"
    }


def test_declared_run_step_outputs_match_hyphenated_inputs_and_keep_spelling():
    specs = {"x/s@v1": mk_spec("x/s@v1", inputs={"wheel_path": {"required": True}})}
    recipe = (
        "on: push\njobs:\n  j:\n    steps:\n"
        "      - {id: p, run: echo, outputs: [wheel-path]}\n"
        "      - {id: s, uses: x/s@v1}\n"
    )
    w = _compile(recipe, specs)["jobs"]["j"]["steps"][1]["with"]
    assert w == {"wheel_path": "${{ steps.p.outputs.wheel-path }}"}


def test_action_yml_spelling_wins_over_a_differently_spelled_declaration():
    specs = {
        "x/p@v1": mk_spec("x/p@v1", outputs=["wheel-path"]),
        "x/s@v1": mk_spec("x/s@v1", inputs={"wheel-path": {"required": True}}),
    }
    recipe = (
        "on: push\njobs:\n  j:\n    steps:\n"
        "      - {id: p, uses: x/p@v1, outputs: [wheel_path]}\n"
        "      - {id: s, uses: x/s@v1}\n"
    )
    w = _compile(recipe, specs)["jobs"]["j"]["steps"][1]["with"]
    assert w == {"wheel-path": "${{ steps.p.outputs.wheel-path }}"}



def test_cross_job_edges_are_found_without_config():
    specs = {
        "x/a@v1": mk_spec("x/a@v1", outputs=["wheel_path"]),
        "x/b@v1": mk_spec("x/b@v1", inputs={"wheel_path": {"required": True}}),
    }
    recipe = (
        "on: push\njobs:\n  build:\n    steps: [{id: bld, uses: x/a@v1}]\n"
        "  test:\n    steps: [{id: t, uses: x/b@v1}]\n"
    )
    wf = _compile(recipe, specs)
    assert wf["jobs"]["test"]["needs"] == ["build"]
    assert wf["jobs"]["build"]["outputs"] == {
        "wheel_path": "${{ steps.bld.outputs.wheel_path }}"
    }
    assert wf["jobs"]["test"]["steps"][0]["with"] == {
        "wheel_path": "${{ needs.build.outputs.wheel_path }}"
    }


# -- mutation-hardening: behaviours the cases above do not distinguish --------


def test_a_step_is_never_wired_from_a_later_step():
    specs = {
        "x/p@v1": mk_spec("x/p@v1", outputs=["v"]),
        "x/s@v1": mk_spec("x/s@v1", inputs={"v": {"required": True}}),
    }
    recipe = "on: push\njobs:\n  j:\n    steps: [{id: s, uses: x/s@v1}, {id: p, uses: x/p@v1}]\n"
    assert "with" not in _compile(recipe, specs)["jobs"]["j"]["steps"][0]


def test_cross_job_edges_skip_inputs_sourced_from_config_or_explicit_with():
    specs = {
        "x/a@v1": mk_spec("x/a@v1", outputs=["v"]),
        "x/b@v1": mk_spec("x/b@v1", inputs={"v": {}}),
    }
    for step, cfg in (
        ("{id: t, uses: x/b@v1}", {"v": 1}),
        ("{id: t, uses: x/b@v1, with: {v: 1}}", {"k": 1}),
    ):
        recipe = (
            "on: push\njobs:\n  build:\n    steps: [{id: bld, uses: x/a@v1}]\n"
            f"  test:\n    steps: [{step}]\n"
        )
        wf = _compile(recipe, specs, config=cfg)
        assert "build" not in wf["jobs"]["test"]["needs"]
        assert "outputs" not in wf["jobs"]["build"]


def test_cross_job_first_matching_job_wins_and_job_outputs_use_source_names():
    specs = {
        "x/a@v1": mk_spec("x/a@v1", outputs=["v"]),
        "x/b@v1": mk_spec("x/b@v1", inputs={"target": {"required": True}}),
    }
    recipe = (
        "on: push\njobs:\n  one:\n    steps: [{id: o, uses: x/a@v1}]\n"
        "  two:\n    steps: [{id: w, uses: x/a@v1}]\n"
        "  use:\n    steps: [{id: t, uses: x/b@v1, bind: {target: v}}]\n"
    )
    wf = _compile(recipe, specs, config={"k": 1})
    assert wf["jobs"]["use"]["needs"] == ["setup", "one"]
    assert "two" not in wf["jobs"]["use"]["needs"]
    assert wf["jobs"]["one"]["outputs"] == {
        "v": "${{ steps.o.outputs.v }}"
    }  # source name, not 'target'


def test_config_refs_inside_lists_and_nested_strategy_values_are_rewritten():
    recipe = (
        "on: push\njobs:\n  j:\n    strategy:\n      matrix:\n"
        "        include: [{py: '${{ config.py }}'}]\n    steps: [{name: Named, run: echo}]\n"
    )
    j = _compile(recipe, {}, config={"py": 1})["jobs"]["j"]
    assert j["strategy"]["matrix"]["include"] == [
        {"py": "${{ needs.setup.outputs.py }}"}
    ]
    assert j["steps"][0]["name"] == "Named"


def test_serialize_config_value_types():
    from reci.compiler import _serialize_config_value as ser

    assert ser({"a": [1]}) == '{"a": [1]}' and ser(["x"]) == '["x"]'
    assert (ser(True), ser(False), ser(3), ser("s")) == ("true", "false", "3", "s")


def test_bind_matches_hyphenated_names_on_either_side():
    specs = {
        "x/p@v1": mk_spec("x/p@v1", outputs=["wheel-path"]),
        "x/s@v1": mk_spec("x/s@v1", inputs={"root-dir": {"required": True}}),
    }
    recipe = (
        "on: push\njobs:\n  j:\n    steps:\n      - {id: p, uses: x/p@v1}\n"
        "      - {id: s, uses: x/s@v1, bind: {root-dir: wheel-path}}\n"
    )
    w = _compile(recipe, specs)["jobs"]["j"]["steps"][1]["with"]
    assert w == {"root-dir": "${{ steps.p.outputs.wheel-path }}"}
    # the normalized spelling in bind: is the same thing
    recipe2 = recipe.replace("{root-dir: wheel-path}", "{root_dir: wheel_path}")
    assert _compile(recipe2, specs)["jobs"]["j"]["steps"][1]["with"] == w


def test_declared_specs_keep_original_spelling():
    from reci.action_spec import action_spec_from_declaration

    spec = action_spec_from_declaration(
        "x/r@v1", inputs={"root-dir": {"required": True}}, outputs=["wheel-path"]
    )
    assert spec.inputs["root_dir"].emitted_name == "root-dir"
    assert spec.outputs["wheel_path"].emitted_name == "wheel-path"
