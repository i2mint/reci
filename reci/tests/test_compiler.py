"""Compiler: golden workflows, five-level input wiring, cross-job forwarding.

The goldens are the point of this file: ``reci`` emits CI that gates other
repos' publishing, so a change that quietly alters the emitted YAML must show up
as a failing diff here. Update a golden only when the change is intended.
"""

import pytest

from reci.compiler import _rewrite_config_refs, compile_recipe
from reci.recipe import parse_recipe_string
from reci.yaml_gen import dump_workflow

from reci.tests._helpers import mk_spec


def _compile(recipe_yaml, specs, config=None):
    return compile_recipe(parse_recipe_string(recipe_yaml), specs, config=config)


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
          echo "python_version=3.12" >> $GITHUB_OUTPUT
          echo "acme_ci_extra=a b" >> $GITHUB_OUTPUT
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
env: {TOP: "${{ config.top }}"}
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
    wf = _compile(recipe, {"x/s@v1": mk_spec("x/s@v1")}, config={"top": 1})
    j = wf["jobs"]["j"]
    n = "needs.setup.outputs"
    assert j["if"] == f"${{{{ {n}.gate }}}}"
    assert j["env"] == {"E": f"${{{{ {n}.e }}}}"}
    assert j["steps"][0]["run"] == f"echo ${{{{ {n}.cmd }}}}"
    assert j["steps"][0]["if"] == f"${{{{ {n}.s_if }}}}"
    assert j["steps"][0]["env"] == {"K": f"${{{{ {n}.k }}}}"}
    assert j["steps"][1]["with"] == {"a": f"${{{{ {n}.a }}}}"}
    # `fromJson(config.x)` is not the ${{ config.x }} form: left untouched
    assert "config.versions" in j["strategy"]["matrix"]["py"]


def test_rewrite_config_refs_tolerates_whitespace_and_leaves_other_contexts():
    assert _rewrite_config_refs("${{config.x}} ${{ github.sha }}") == (
        "${{ needs.setup.outputs.x }} ${{ github.sha }}"
    )


def test_setup_job_serializes_values_by_type():
    wf = _compile(
        "on: push\njobs:\n  j:\n    steps:\n      - run: echo\n",
        {},
        config={"lst": ["3.10", "3.12"], "flag": True, "off": False, "n": 3},
    )
    run = wf["jobs"]["setup"]["steps"][0]["run"]
    assert 'echo "lst=["3.10", "3.12"]" >> $GITHUB_OUTPUT' in run
    assert 'echo "flag=true" >> $GITHUB_OUTPUT' in run
    assert 'echo "off=false" >> $GITHUB_OUTPUT' in run
    assert 'echo "n=3" >> $GITHUB_OUTPUT' in run
    assert list(wf["jobs"]["setup"]["outputs"]) == ["lst", "flag", "off", "n"]


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


@pytest.mark.xfail(
    strict=True, reason="i2mint/reci#8: needs 'setup' without a setup job"
)
def test_no_config_means_no_dangling_needs_setup():
    wf = _compile("on: push\njobs:\n  j:\n    steps: [{run: echo}]\n", {})
    assert "setup" in wf["jobs"] or "setup" not in wf["jobs"]["j"]["needs"]


@pytest.mark.xfail(strict=True, reason="i2mint/reci#9: cross-job expression is garbled")
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


def test_cross_job_forwarding_adds_needs_and_job_outputs():
    """The parts of cross-job wiring that do work today (the expression is #9)."""
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


@pytest.mark.xfail(
    strict=True, reason="i2mint/reci#10: hyphens in action input ids are lost"
)
def test_hyphenated_action_input_keeps_its_spelling():
    specs = {"x/s@v1": mk_spec("x/s@v1", inputs={"root-dir": {"required": True}})}
    wf = _compile(
        "on: push\njobs:\n  j:\n    steps: [{id: s, uses: x/s@v1}]\n",
        specs,
        config={"root_dir": "."},
    )
    assert "root-dir" in wf["jobs"]["j"]["steps"][0]["with"]
