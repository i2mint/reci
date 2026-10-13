"""Graph structure, config resolution, and action-spec parsing/fetching."""

import httpx
import pytest

from reci.action_spec import (
    InputSpec,
    ActionFetchError,
    _parse_ref,
    action_local_name,
    action_spec_from_declaration,
    action_spec_from_ref,
    normalize_name,
    parse_action_spec,
)
from reci.config import (
    collect_required_config_keys,
    flatten_config,
    resolve_config_for_input,
)
from reci.graph import RecipeGraph
from reci.recipe import parse_recipe_string
from reci.tests._helpers import mk_graph, mk_spec

# -- graph -------------------------------------------------------------------

TWO_JOBS = """\
on: push
jobs:
  a:
    steps: [{id: a1, run: echo}, {id: a2, run: echo}]
  b:
    needs: [a]
    steps: [{id: b1, run: echo}]
"""


def test_steps_are_sequential_and_jobs_chain_on_needs():
    g = mk_graph(TWO_JOBS)
    assert g.job_ids() == ["a", "b"]
    assert g.predecessors("a.a2") == {"a.a1"}
    assert g.predecessors("b.b1") == {"a.a2"}  # first step waits for last of `a`
    assert g.execution_waves() == [("a.a1",), ("a.a2",), ("b.b1",)]


def test_independent_jobs_share_a_wave():
    g = mk_graph(
        "on: push\njobs:\n  x:\n    steps: [{id: s, run: e}]\n"
        "  y:\n    steps: [{id: s, run: e}]\n"
    )
    (wave,) = g.execution_waves()
    assert sorted(wave) == ["x.s", "y.s"]


def test_node_output_names_merge_declared_and_action_outputs_without_duplicates():
    specs = {"x/a@v1": mk_spec("x/a@v1", outputs=["wheel", "sha"])}
    g = mk_graph(
        "on: push\njobs:\n  j:\n    steps: [{id: s, uses: x/a@v1, outputs: [sha, extra]}]\n",
        specs,
    )
    assert g["j.s"].output_names == ["sha", "extra", "wheel"]
    assert g["j.s"].input_specs == {}


def test_cyclic_needs_fail_execution_waves_and_validation():
    from graphlib import CycleError

    g = mk_graph(
        "on: push\njobs:\n  a:\n    needs: [b]\n    steps: [{run: e}]\n"
        "  b:\n    needs: [a]\n    steps: [{run: e}]\n"
    )
    with pytest.raises(CycleError):
        g.execution_waves()
    assert [
        f.rule_id for f in g.validate().findings if f.severity.value == "error"
    ] == ["DAG001"]


def test_needs_on_unknown_job_is_ignored_by_the_graph():
    g = mk_graph(
        "on: push\njobs:\n  a:\n    needs: [ghost]\n    steps: [{id: s, run: e}]\n"
    )
    assert g.predecessors("a.s") == set()


# -- config ------------------------------------------------------------------


def test_flatten_config_uses_double_underscore_and_keeps_lists():
    assert flatten_config({"t": {"py": ["3.10"], "deep": {"x": 1}}, "top": 2}) == {
        "t__py": ["3.10"],
        "t__deep__x": 1,
        "top": 2,
    }


def test_resolve_config_scoped_then_shared_then_none():
    cfg = {"run_tests__root": "scoped", "root": "shared"}
    assert resolve_config_for_input("root", "o/r/actions/run-tests@v1", cfg) == (
        "run_tests__root",
        "scoped",
    )
    assert resolve_config_for_input("root", "o/r/actions/other@v1", cfg) == (
        "root",
        "shared",
    )
    assert resolve_config_for_input("root", None, {"x": 1}) is None


def test_collect_required_config_keys():
    specs = {
        "x/a@v1": mk_spec(
            "x/a@v1",
            inputs={
                "need": {"required": True},
                "has-default": {"required": True, "default": "d"},
                "opt": {},
                "given": {"required": True},
            },
        ),
        "x/b@v1": mk_spec("x/b@v1", inputs={"opt": {"required": True}}),
    }
    recipe = parse_recipe_string(
        "on: push\njobs:\n  j:\n    steps:\n"
        "      - {uses: x/a@v1, with: {given: 1}}\n      - {uses: x/b@v1}\n      - run: e\n"
    )
    assert collect_required_config_keys(recipe, specs) == {
        "need": True,
        "has_default": False,
        "opt": True,  # optional in a, required in b -> required wins
    }


def test_collect_required_config_keys_skips_upstream_fed_inputs():
    specs = {
        "x/p@v1": mk_spec("x/p@v1", outputs=["wheel", "artifact"]),
        "x/c@v1": mk_spec(
            "x/c@v1",
            inputs={
                "wheel": {"required": True},
                "path": {"required": True},
                "other": {"required": True},
                "later": {"required": True},
            },
            outputs=["later"],
        ),
    }
    recipe = parse_recipe_string(
        "on: push\njobs:\n  build:\n    steps: [{id: p, uses: x/p@v1}]\n"
        "  test:\n    steps:\n"
        "      - {id: c1, uses: x/c@v1, bind: {path: artifact}}\n"
        "      - {id: c2, uses: x/c@v1, bind: {path: artifact}}\n"
    )
    # wheel/artifact come from job `build`; `later` is produced by c1 so only
    # c2 gets it; c1 still needs it from config.
    assert collect_required_config_keys(recipe, specs) == {
        "other": True,
        "later": True,
    }


def test_collect_required_config_keys_cross_job_consumer_adds_no_requirement():
    # Scaffold writes only required keys, so a consumer fed by another job's
    # output must not turn another step's optional `wheel` into a written key
    # (it would override the cross-job output with a placeholder).
    specs = {
        "x/p@v1": mk_spec("x/p@v1", inputs={"wheel": {}}, outputs=["wheel"]),
        "x/c@v1": mk_spec("x/c@v1", inputs={"wheel": {"required": True}}),
    }
    recipe = parse_recipe_string(
        "on: push\njobs:\n  build:\n    steps: [{id: p, uses: x/p@v1}]\n"
        "  test:\n    steps: [{id: c, uses: x/c@v1}]\n"
    )
    assert collect_required_config_keys(recipe, specs) == {"wheel": False}


def test_upstream_output_names_is_scoped_by_job_even_for_equal_step_ids():
    specs = {
        "x/p@v1": mk_spec("x/p@v1", outputs=["v"]),
        "x/c@v1": mk_spec("x/c@v1", inputs={"v": {"required": True}}),
    }
    recipe = parse_recipe_string(
        "on: push\njobs:\n  a:\n    steps: [{id: s, uses: x/c@v1}]\n"
        "  b:\n    steps: [{id: s, uses: x/p@v1}]\n"
    )
    graph = RecipeGraph.from_recipe(recipe, specs)
    node = graph["a.s"]
    assert graph.upstream_output_names(node, other_jobs=False) == set()
    assert graph.upstream_output_names(node) == {"v"}  # b.s is another job


def test_collect_required_config_keys_includes_explicit_config_references():
    recipe = parse_recipe_string(
        "on: push\nenv: {W: '${{ config.not_needed_here }}'}\njobs:\n  j:\n"
        "    runs-on: ${{ config.os }}\n"
        "    steps: [{run: 'echo ${{ config.msg }} config.json'}]\n"
    )
    # workflow env cannot use config at all (CONF004), so it asks for nothing
    assert collect_required_config_keys(recipe, {}) == {"os": True, "msg": True}


# -- action specs -------------------------------------------------------------


def test_normalize_and_local_name():
    assert normalize_name("  Root-Dir x ") == "root_dir_x"
    assert action_local_name("i2mint/wads/actions/run-tests@master") == "run_tests"
    assert action_local_name("run-tests") == "run_tests"


@pytest.mark.parametrize(
    "ref, expected",
    [
        ("a/b", ("a", "b", "", "main")),
        ("a/b/c/d@v1", ("a", "b", "c/d", "v1")),
        ("a", ("a", "", "", "main")),
    ],
)
def test_parse_ref(ref, expected):
    assert _parse_ref(ref) == expected


def test_parse_action_spec_normalizes_and_coerces_required():
    spec = parse_action_spec(
        "x/y@v1",
        action_yml_data={
            "inputs": {
                "Root-Dir": {"required": "true", "default": ".", "description": 5},
                "flag": {"required": "no"},
                "bare": None,
            },
            "outputs": {"New-Version": {"description": "v"}},
        },
    )
    assert set(spec.inputs) == {"root_dir", "flag", "bare"}
    assert spec.inputs["root_dir"].required is True
    assert (
        spec.inputs["root_dir"].default == "."
        and spec.inputs["root_dir"].description == "5"
    )
    assert (
        spec.inputs["flag"].required is False and spec.inputs["bare"].required is False
    )
    assert list(spec.outputs) == ["new_version"]


@pytest.mark.parametrize(
    "raw, expected",
    [("yes", True), ("1", True), ("TRUE", True), ("no", False), (1, True), (0, False)],
)
def test_required_flag_coercion(raw, expected):
    spec = parse_action_spec(
        "x/y@v1", action_yml_data={"inputs": {"a": {"required": raw}}}
    )
    assert spec.inputs["a"].required is expected


def test_parse_action_spec_without_inputs_or_outputs():
    spec = parse_action_spec("x/y@v1", action_yml_data={"name": "n"})
    assert spec.inputs == {} and spec.outputs == {}


def test_action_spec_from_declaration():
    spec = action_spec_from_declaration(
        "local", inputs={"A-b": {"required": True}}, outputs=["Out-Put"]
    )
    assert spec.inputs["a_b"].required and list(spec.outputs) == ["out_put"]
    assert action_spec_from_declaration("x").inputs == {}
    spec2 = action_spec_from_declaration(
        "local", inputs={"k": {"default": "d", "description": "dd"}}
    )
    assert (spec2.inputs["k"].default, spec2.inputs["k"].description) == ("d", "dd")


class _Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


def test_fetch_tries_action_yml_then_action_yaml(monkeypatch):
    seen = []

    def fake_get(url, **kw):
        assert kw.get("follow_redirects") is True and kw.get("timeout")
        seen.append(url)
        if url.endswith("action.yaml"):
            return _Resp(200, "inputs:\n  a-b:\n    required: true\n")
        return _Resp(404)

    monkeypatch.setattr(httpx, "get", fake_get)
    spec = action_spec_from_ref("o/r/sub/dir@v2")
    assert seen == [
        "https://raw.githubusercontent.com/o/r/v2/sub/dir/action.yml",
        "https://raw.githubusercontent.com/o/r/v2/sub/dir/action.yaml",
    ]
    assert spec.ref == "o/r/sub/dir@v2" and spec.inputs["a_b"].required


def test_fetch_failure_lists_urls_and_survives_http_errors(monkeypatch):
    def boom(url, **kw):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", boom)
    with pytest.raises(ActionFetchError, match=r"action\.yml.*\n.*action\.yaml"):
        action_spec_from_ref("o/r@v1")


def test_specs_keep_the_original_spelling_next_to_the_normalized_name():
    spec = mk_spec("x/a@v1", inputs={"Root-Dir": {}}, outputs=["wheel-path"])
    assert spec.inputs["root_dir"].original_name == "Root-Dir"
    assert spec.inputs["root_dir"].emitted_name == "Root-Dir"
    assert spec.outputs["wheel_path"].emitted_name == "wheel-path"
    # hand-built specs without an original fall back to the normalized name
    assert InputSpec(name="a_b").emitted_name == "a_b"
