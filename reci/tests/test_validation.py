"""Validation rules: one reject case and one accept case per rule, plus the runner."""

import json

import pytest

from reci.tests._helpers import mk_graph, mk_spec
from reci.validation.formatters import (
    format_cli,
    format_github_annotations,
    format_json,
)
from reci.validation.report import Finding, Severity, ValidationReport
from reci.validation.rules import run_all_rules


def _ids(graph, config=None, **kw):
    return sorted(f.rule_id for f in run_all_rules(graph, config or {}, **kw).findings)


def _steps(*steps):
    body = "".join(f"      - {s}\n" for s in steps)
    return f"on: push\njobs:\n  j:\n    steps:\n{body}"


def _only(rule, graph, config=None):
    return [f for f in run_all_rules(graph, config or {}).findings if f.rule_id == rule]


# -- ACT002 --------------------------------------------------------------------


def test_ACT002_unresolved_action_rejected_resolved_accepted():
    recipe = _steps("{id: s, uses: x/a@v1}")
    (f,) = _only("ACT002", mk_graph(recipe))
    assert f.severity is Severity.ERROR and f.location == "j.s"
    assert _only("ACT002", mk_graph(recipe, {"x/a@v1": mk_spec("x/a@v1")})) == []
    assert _only("ACT002", mk_graph(_steps("{run: echo}"))) == []  # run: has no ref


# -- DAG ------------------------------------------------------------------------


def test_DAG001_cycle():
    cyc = (
        "on: push\njobs:\n  a:\n    needs: [b]\n    steps: [{run: e}]\n"
        "  b:\n    needs: [a]\n    steps: [{run: e}]\n"
    )
    (f,) = _only("DAG001", mk_graph(cyc))
    assert f.severity is Severity.ERROR and "Cycle detected" in f.message
    assert _only("DAG001", mk_graph(_steps("{run: e}"))) == []


def test_DAG002_duplicate_output_names_in_a_job():
    specs = {"x/a@v1": mk_spec("x/a@v1", outputs=["v"])}
    dup = _steps("{id: one, uses: x/a@v1}", "{id: two, uses: x/a@v1}")
    (f,) = _only("DAG002", mk_graph(dup, specs))
    assert f.severity is Severity.ERROR and "one, two" in f.message
    assert _only("DAG002", mk_graph(_steps("{id: one, uses: x/a@v1}"), specs)) == []


def test_DAG004_isolated_action_node():
    specs = {"x/a@v1": mk_spec("x/a@v1")}
    (f,) = _only("DAG004", mk_graph(_steps("{id: s, uses: x/a@v1}"), specs))
    assert f.severity is Severity.WARNING
    assert _only("DAG004", mk_graph(_steps("{run: echo}"))) == []  # run: exempt
    wired = {
        "x/a@v1": mk_spec("x/a@v1", outputs=["v"]),
        "x/b@v1": mk_spec("x/b@v1", inputs={"v": {}}),
    }
    g = mk_graph(_steps("{id: p, uses: x/a@v1}", "{id: c, uses: x/b@v1}"), wired)
    assert _only("DAG004", g) == []


# -- FLOW -----------------------------------------------------------------------

NEEDS_V = {"x/s@v1": mk_spec("x/s@v1", inputs={"v": {"required": True}})}


def test_FLOW001_required_input_needs_a_source_at_some_level():
    g = mk_graph(_steps("{id: s, uses: x/s@v1}"), NEEDS_V)
    (f,) = _only("FLOW001", g)
    assert f.severity is Severity.ERROR and "'v'" in f.message
    assert _only("FLOW001", g, {"v": 1}) == []  # config
    assert _only("FLOW001", g, {"s__v": 1}) == []  # scoped config
    explicit = mk_graph(_steps("{id: s, uses: x/s@v1, with: {v: 1}}"), NEEDS_V)
    assert _only("FLOW001", explicit) == []
    dflt = {
        "x/s@v1": mk_spec("x/s@v1", inputs={"v": {"required": True, "default": "d"}})
    }
    assert _only("FLOW001", mk_graph(_steps("{id: s, uses: x/s@v1}"), dflt)) == []
    up = {**NEEDS_V, "x/p@v1": mk_spec("x/p@v1", outputs=["v"])}
    assert (
        _only(
            "FLOW001",
            mk_graph(_steps("{id: p, uses: x/p@v1}", "{id: s, uses: x/s@v1}"), up),
        )
        == []
    )
    bound = mk_graph(
        _steps(
            "{id: p, run: e, outputs: [other]}",
            "{id: s, uses: x/s@v1, bind: {v: other}}",
        ),
        NEEDS_V,
    )
    assert _only("FLOW001", bound) == []


def test_FLOW002_ambiguous_upstream_producers_warn():
    specs = {
        "x/p@v1": mk_spec("x/p@v1", outputs=["v"]),
        "x/s@v1": mk_spec("x/s@v1", inputs={"v": {}}),
    }
    amb = _steps(
        "{id: a, uses: x/p@v1}", "{id: b, uses: x/p@v1}", "{id: s, uses: x/s@v1}"
    )
    (f,) = _only("FLOW002", mk_graph(amb, specs))
    assert f.severity is Severity.WARNING and "a, b" in f.message
    one = _steps("{id: a, uses: x/p@v1}", "{id: s, uses: x/s@v1}")
    assert _only("FLOW002", mk_graph(one, specs)) == []


def test_FLOW004_unconsumed_output_is_info():
    specs = {"x/p@v1": mk_spec("x/p@v1", outputs=["v"])}
    (f,) = _only("FLOW004", mk_graph(_steps("{id: p, uses: x/p@v1}"), specs))
    assert f.severity is Severity.INFO
    specs["x/s@v1"] = mk_spec("x/s@v1", inputs={"v": {}})
    used = mk_graph(_steps("{id: p, uses: x/p@v1}", "{id: s, uses: x/s@v1}"), specs)
    assert _only("FLOW004", used) == []


def test_FLOW005_string_output_into_boolean_input_warns():
    specs = {
        "x/p@v1": mk_spec("x/p@v1", outputs=["flag"]),
        "x/s@v1": mk_spec("x/s@v1", inputs={"flag": {"default": "false"}}),
    }
    g = mk_graph(_steps("{id: p, uses: x/p@v1}", "{id: s, uses: x/s@v1}"), specs)
    (f,) = _only("FLOW005", g)
    assert f.severity is Severity.WARNING and f.suggestion
    explicit = _steps(
        "{id: p, uses: x/p@v1}", "{id: s, uses: x/s@v1, with: {flag: 'true'}}"
    )
    assert _only("FLOW005", mk_graph(explicit, specs)) == []
    nonbool = {**specs, "x/s@v1": mk_spec("x/s@v1", inputs={"flag": {"default": "x"}})}
    assert (
        _only(
            "FLOW005",
            mk_graph(_steps("{id: p, uses: x/p@v1}", "{id: s, uses: x/s@v1}"), nonbool),
        )
        == []
    )


# -- CONF -----------------------------------------------------------------------


def test_CONF001_missing_required_config():
    g = mk_graph(_steps("{id: s, uses: x/s@v1}"), NEEDS_V)
    (f,) = _only("CONF001", g)
    assert f.severity is Severity.ERROR and "'v'" in f.message
    assert _only("CONF001", g, {"v": 1}) == []
    assert _only("CONF001", g, {"s__v": 1}) == []


def test_CONF003_unused_config_key_is_info():
    g = mk_graph(_steps("{id: s, uses: x/s@v1}"), NEEDS_V)
    findings = _only("CONF003", g, {"v": 1, "s__v": 2, "stray": 3})
    assert [f.message for f in findings] == [
        "Config key 'stray' is not referenced by any action input."
    ]
    assert all(f.severity is Severity.INFO for f in findings)


# -- PURE -----------------------------------------------------------------------


def test_PURE001_run_step_warns_action_step_does_not():
    (f,) = _only("PURE001", mk_graph(_steps("{id: r, run: echo hi}")))
    assert f.severity is Severity.WARNING and f.location == "j.r"
    specs = {"x/a@v1": mk_spec("x/a@v1")}
    assert _only("PURE001", mk_graph(_steps("{uses: x/a@v1}"), specs)) == []


@pytest.mark.parametrize(
    "script",
    [
        'echo "v=1" >> $GITHUB_OUTPUT',
        "echo v=1 >> ${GITHUB_OUTPUT}",
        'echo v=1 >> "$GITHUB_OUTPUT"',
    ],
)
def test_PURE002_undeclared_github_output_write(script):
    # a YAML block scalar keeps any quoting in `script` intact
    recipe = (
        "on: push\njobs:\n  j:\n    steps:\n      - id: r\n        run: |\n          "
        + script
        + "\n"
    )
    (f,) = _only("PURE002", mk_graph(recipe))
    assert f.severity is Severity.INFO
    declared = recipe + "        outputs: [v]\n"
    assert _only("PURE002", mk_graph(declared)) == []


def test_PURE002_plain_run_without_output_write_is_fine():
    assert _only("PURE002", mk_graph(_steps("{id: r, run: make}"))) == []


# -- runner ---------------------------------------------------------------------


def test_run_all_rules_severity_override_and_disable():
    g = mk_graph(_steps("{id: r, run: make}"))
    assert _ids(g) == ["PURE001"]
    assert _ids(g, disabled_rules={"PURE001"}) == []
    assert _ids(g, severity_overrides={"PURE001": "off"}) == []
    rep = run_all_rules(g, {}, severity_overrides={"PURE001": "error"})
    assert rep.has_errors and rep.findings[0].severity is Severity.ERROR
    assert rep.findings[0].message  # other fields survive the override


def test_a_clean_pipeline_has_no_errors(pipeline_recipe_yaml, pipeline_specs):
    g = mk_graph(pipeline_recipe_yaml, pipeline_specs)
    rep = g.validate({"python_version": "3.12"})
    assert not rep.has_errors, [f.message for f in rep.findings]


# -- report + formatters -------------------------------------------------------

_REPORT = ValidationReport(
    findings=[
        Finding("E1", Severity.ERROR, "bad", location="j.s", suggestion="fix it"),
        Finding("W1", Severity.WARNING, "meh"),
        Finding("I1", Severity.INFO, "fyi", location="j.t", fixable=True),
    ]
)


def test_report_counts_filters_and_merge():
    assert (_REPORT.error_count, _REPORT.warning_count) == (1, 1)
    assert _REPORT.has_errors and not ValidationReport().has_errors
    assert [f.rule_id for f in _REPORT.findings_by_severity(Severity.INFO)] == ["I1"]
    assert [f.rule_id for f in _REPORT.findings_by_rule("W")] == ["W1"]
    assert len(_REPORT.merge(_REPORT).findings) == 6


def test_format_cli():
    assert format_cli(ValidationReport()) == "No issues found."
    out = format_cli(_REPORT)
    assert "E1: bad\n  --> j.s\n  = help: fix it" in out
    assert out.endswith("1 error(s), 1 warning(s), 3 total")


def test_format_json_round_trips():
    items = json.loads(format_json(_REPORT))
    assert [i["rule_id"] for i in items] == ["E1", "W1", "I1"]
    assert items[0]["severity"] == "error" and items[2]["fixable"] is True
    assert items[1]["location"] is None


def test_format_github_annotations_levels():
    assert format_github_annotations(_REPORT).splitlines() == [
        "::error file=j.s::[E1] bad",
        "::warning::[W1] meh",
        "::notice file=j.t::[I1] fyi",
    ]


# -- mutation-hardening: each exemption path of a rule, one at a time -----------


def test_CONF001_is_satisfied_by_default_explicit_with_or_bind_individually():
    dflt = {
        "x/s@v1": mk_spec("x/s@v1", inputs={"v": {"required": True, "default": "d"}})
    }
    assert _only("CONF001", mk_graph(_steps("{id: s, uses: x/s@v1}"), dflt)) == []
    explicit = mk_graph(_steps("{id: s, uses: x/s@v1, with: {v: 1}}"), NEEDS_V)
    assert _only("CONF001", explicit) == []
    bound = mk_graph(
        _steps(
            "{id: p, run: e, outputs: [other]}",
            "{id: s, uses: x/s@v1, bind: {v: other}}",
        ),
        NEEDS_V,
    )
    assert _only("CONF001", bound) == []
    up = {**NEEDS_V, "x/p@v1": mk_spec("x/p@v1", outputs=["v"])}
    assert (
        _only(
            "CONF001",
            mk_graph(_steps("{id: p, uses: x/p@v1}", "{id: s, uses: x/s@v1}"), up),
        )
        == []
    )
    # an upstream producer that comes *later* does not count
    late = mk_graph(_steps("{id: s, uses: x/s@v1}", "{id: p, uses: x/p@v1}"), up)
    assert len(_only("CONF001", late)) == 1


def test_CONF003_ignores_config_for_inputs_given_explicitly():
    g = mk_graph(_steps("{id: s, uses: x/s@v1, with: {v: 1}}"), NEEDS_V)
    assert [f.message for f in _only("CONF003", g, {"v": 1})] == [
        "Config key 'v' is not referenced by any action input."
    ]


def test_FLOW002_does_not_flag_inputs_given_explicitly():
    specs = {
        "x/p@v1": mk_spec("x/p@v1", outputs=["v"]),
        "x/s@v1": mk_spec("x/s@v1", inputs={"v": {}}),
    }
    recipe = _steps(
        "{id: a, uses: x/p@v1}",
        "{id: b, uses: x/p@v1}",
        "{id: s, uses: x/s@v1, with: {v: 1}}",
    )
    assert _only("FLOW002", mk_graph(recipe, specs)) == []


def test_FLOW005_follows_bind_and_accepts_yaml_boolean_defaults():
    specs = {
        "x/p@v1": mk_spec("x/p@v1", outputs=["out"]),
        "x/s@v1": mk_spec("x/s@v1", inputs={"flag": {"default": "True"}}),
    }
    bound = _steps("{id: p, uses: x/p@v1}", "{id: s, uses: x/s@v1, bind: {flag: out}}")
    assert (
        len(_only("FLOW005", mk_graph(bound, specs))) == 1
    )  # 'True' counts as boolean
    unbound_name = _steps("{id: p, uses: x/p@v1}", "{id: s, uses: x/s@v1}")
    assert _only("FLOW005", mk_graph(unbound_name, specs)) == []


def test_FLOW004_counts_an_explicit_steps_reference_as_consumption():
    specs = {
        "x/p@v1": mk_spec("x/p@v1", outputs=["v"]),
        "x/s@v1": mk_spec("x/s@v1", inputs={"other": {}}),
    }
    recipe = _steps(
        "{id: p, uses: x/p@v1}",
        "{id: s, uses: x/s@v1, with: {other: '${{ steps.p.outputs.v }}'}}",
    )
    assert _only("FLOW004", mk_graph(recipe, specs)) == []


@pytest.mark.parametrize(
    "where",
    [
        "with: {other: '${{ steps.p.outputs.v }}'}",
        "env: {E: '${{ steps.p.outputs.v }}'}",
        "if: '${{ steps.p.outputs.v }}'",
    ],
)
def test_FLOW004_counts_references_in_with_env_and_if(where):
    specs = {
        "x/p@v1": mk_spec("x/p@v1", outputs=["v"]),
        "x/s@v1": mk_spec("x/s@v1", inputs={"other": {}}),
    }
    recipe = _steps("{id: p, uses: x/p@v1}", f"{{id: s, uses: x/s@v1, {where}}}")
    assert _only("FLOW004", mk_graph(recipe, specs)) == []


def test_FLOW004_counts_run_references_and_normalizes_names():
    specs = {"x/p@v1": mk_spec("x/p@v1", outputs=["wheel-path"])}
    recipe = _steps(
        "{id: p, uses: x/p@v1}",
        "{id: r, run: 'echo ${{ steps.p.outputs.wheel-path }}'}",
    )
    assert _only("FLOW004", mk_graph(recipe, specs)) == []


def test_FLOW004_needs_references_do_not_count_as_consumption():
    specs = {"x/p@v1": mk_spec("x/p@v1", outputs=["v"])}
    recipe = (
        "on: push\njobs:\n  a:\n    steps: [{id: p, uses: x/p@v1}]\n"
        "  b:\n    needs: a\n"
        "    steps: [{id: r, run: 'echo ${{ needs.a.outputs.v }}'}]\n"
    )
    assert [f.location for f in _only("FLOW004", mk_graph(recipe, specs))] == ["a.p"]


def test_FLOW004_steps_reference_is_scoped_to_its_own_job():
    specs = {"x/p@v1": mk_spec("x/p@v1", outputs=["v"])}
    recipe = (
        "on: push\njobs:\n  a:\n    steps: [{id: p, uses: x/p@v1}]\n"
        "  b:\n    steps:\n      - {id: p, uses: x/p@v1}\n"
        "      - {id: r, run: 'echo ${{ steps.p.outputs.v }}'}\n"
    )
    assert [f.location for f in _only("FLOW004", mk_graph(recipe, specs))] == ["a.p"]


def test_FLOW004_explicit_reference_only_consumes_the_step_it_names():
    specs = {"x/p@v1": mk_spec("x/p@v1", outputs=["v"])}
    recipe = _steps(
        "{id: p1, uses: x/p@v1}",
        "{id: p2, uses: x/p@v1}",
        "{id: r, run: 'echo ${{ steps.p2.outputs.v }}'}",
    )
    flagged = [f.location for f in _only("FLOW004", mk_graph(recipe, specs))]
    assert flagged == ["j.p1"]


def test_severity_override_keeps_location_and_suggestion():
    g = mk_graph(_steps("{id: r, run: make}"))
    (f,) = run_all_rules(g, {}, severity_overrides={"PURE001": "info"}).findings
    assert f.severity is Severity.INFO and f.location == "j.r" and f.suggestion


def test_DAG002_reports_the_job_as_location():
    specs = {"x/a@v1": mk_spec("x/a@v1", outputs=["v"])}
    g = mk_graph(_steps("{id: one, uses: x/a@v1}", "{id: two, uses: x/a@v1}"), specs)
    assert _only("DAG002", g)[0].location == "j"


# -- DAG005: needs cycles made by data flow -------------------------------------

_LOOP_SPECS = {
    "x/a@v1": mk_spec("x/a@v1", inputs={"w": {"required": True}}, outputs=["v"]),
    "x/b@v1": mk_spec("x/b@v1", inputs={"v": {"required": True}}, outputs=["w"]),
}


def test_DAG005_jobs_that_consume_each_others_outputs_form_a_cycle():
    recipe = (
        "on: push\njobs:\n  a:\n    steps: [{id: s, uses: x/a@v1}]\n"
        "  b:\n    steps: [{id: t, uses: x/b@v1}]\n"
    )
    (f,) = _only("DAG005", mk_graph(recipe, _LOOP_SPECS))
    assert "a -> b -> a" in f.message or "b -> a -> b" in f.message
    assert "'b.t' reads 'v' from 'a.s'" in f.message
    assert f.severity is Severity.ERROR


def test_DAG005_explicit_needs_against_the_data_flow_direction_is_a_cycle():
    specs = {
        "x/a@v1": mk_spec("x/a@v1", outputs=["v"]),
        "x/b@v1": mk_spec("x/b@v1", inputs={"v": {"required": True}}),
    }
    recipe = (
        "on: push\njobs:\n  build:\n    needs: test\n"
        "    steps: [{id: p, uses: x/a@v1}]\n"
        "  test:\n    steps: [{id: c, uses: x/b@v1}]\n"
    )
    assert len(_only("DAG005", mk_graph(recipe, specs))) == 1


def test_DAG005_one_way_flow_and_purely_explicit_cycles_are_not_its_business():
    specs = {
        "x/a@v1": mk_spec("x/a@v1", outputs=["v"]),
        "x/b@v1": mk_spec("x/b@v1", inputs={"v": {"required": True}}),
    }
    ok = (
        "on: push\njobs:\n  build:\n    steps: [{id: p, uses: x/a@v1}]\n"
        "  test:\n    needs: build\n    steps: [{id: c, uses: x/b@v1}]\n"
    )
    assert _only("DAG005", mk_graph(ok, specs)) == []
    explicit = (
        "on: push\njobs:\n  a:\n    needs: b\n    steps: [{run: x}]\n"
        "  b:\n    needs: a\n    steps: [{run: x}]\n"
    )
    g = mk_graph(explicit, {})
    assert _only("DAG005", g) == [] and len(_only("DAG001", g)) == 1


# -- recipe-level checks: CONF004, DAG006, DAG007 -------------------------------


def test_CONF004_config_reference_to_a_missing_key():
    recipe = _steps("{id: r, run: 'echo ${{ config.x }} ${{ config.y }}'}")
    g = mk_graph(recipe)
    assert [f.location for f in _only("CONF004", g, {"x": 1})] == ["j.r"]
    assert "config.y" in _only("CONF004", g, {"x": 1})[0].message
    assert _only("CONF004", g, {"x": 1, "y": 2}) == []
    assert len(_only("CONF004", g, {})) == 2  # no config at all: both missing


def test_CONF004_sees_references_in_every_rewritten_field():
    recipe = (
        "on: push\njobs:\n  j:\n"
        "    if: ${{ config.a }}\n    runs-on: ${{ config.os }}\n"
        "    env: {E: '${{ config.e }}'}\n"
        "    strategy: {matrix: {py: ['${{ config.m }}']}}\n"
        "    steps:\n      - {id: s, name: 'n ${{ config.n }}', if: '${{ config.i }}',\n"
        "         run: 'x', env: {K: '${{ config.k }}'}}\n"
    )
    missing = {
        f.message.split("config.")[1].split(",")[0]
        for f in _only("CONF004", mk_graph(recipe), {"unrelated": 1})
    }
    assert missing == {"a", "os", "e", "m", "n", "i", "k"}


def test_CONF004_config_in_workflow_env_or_permissions_is_never_valid():
    recipe = (
        "on: push\nenv: {W: '${{ config.w }}'}\njobs:\n  j:\n"
        "    permissions: {contents: '${{ config.p }}'}\n    steps: [{run: e}]\n"
    )
    found = _only("CONF004", mk_graph(recipe), {"w": 1, "p": 2})  # keys exist
    assert sorted(f.location for f in found) == ["j permissions", "workflow env"]
    assert all("no 'needs' context" in f.message for f in found)


def test_DAG006_needs_unknown_job_but_setup_exists_only_with_config():
    recipe = (
        "on: push\njobs:\n  a:\n    needs: [setup, ghost]\n"
        "    steps: [{run: echo}]\n"
    )
    g = mk_graph(recipe)
    no_config = [f.message for f in _only("DAG006", g)]
    assert len(no_config) == 2 and any("setup job exists only" in m for m in no_config)
    with_config = [f.message for f in _only("DAG006", g, {"k": 1})]
    assert len(with_config) == 1 and "'ghost'" in with_config[0]


def test_DAG007_job_named_setup_is_only_a_clash_when_config_is_supplied():
    g = mk_graph("on: push\njobs:\n  setup:\n    steps: [{run: echo}]\n")
    assert _only("DAG007", g) == []
    (f,) = _only("DAG007", g, {"k": 1})
    assert f.severity is Severity.ERROR and f.location == "setup"
