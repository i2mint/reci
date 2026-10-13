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


def test_CONF004_ignores_text_that_merely_contains_config_dot_something():
    recipe = _steps(
        "{id: r, name: 'Write config.toml', run: 'cat config.json && python -m my.config.x',\n"
        "         env: {CFG: config.yml, G: '${{ github.event.config.x }}'}}"
    )
    assert _only("CONF004", mk_graph(recipe)) == []
    top_env = "on: push\nenv: {CFG: config.yml}\njobs:\n  j:\n    steps: [{run: e}]\n"
    assert _only("CONF004", mk_graph(top_env)) == []


def test_CONF004_sees_with_values_and_reports_a_repeated_reference_once():
    specs = {"x/s@v1": mk_spec("x/s@v1", inputs={"p": {}})}
    recipe = _steps(
        "{id: s, uses: x/s@v1, with: {p: '${{ config.a }}'}}",
        "{id: r, run: 'echo ${{ config.b }} ${{ config.b }}'}",
    )
    found = _only("CONF004", mk_graph(recipe, specs))
    assert sorted(f.location for f in found) == ["j.r", "j.s"]


def test_CONF004_sees_config_refs_inside_expressions_and_hyphenated_keys():
    recipe = _steps(
        "{id: r, if: '${{ fromJson(config.versions) && config.test-on-windows }}', run: e}"
    )
    found = _only("CONF004", mk_graph(recipe), {"versions": 1})
    assert [f.message for f in found] == [
        "'j.r' references config.test-on-windows, which is not a config key."
    ]


def test_CONF004_sees_a_ref_after_a_braces_string_literal():
    recipe = _steps("{id: r, if: \"${{ format('{0} }}', config.nokey) }}\", run: e}")
    (f,) = _only("CONF004", mk_graph(recipe))
    assert "config.nokey" in f.message


# -- FLOW001 / CONF001 know about producers in other jobs ------------------------

_XJOB_SPECS = {
    "x/a@v1": mk_spec("x/a@v1", outputs=["wheel", "other"]),
    "x/b@v1": mk_spec("x/b@v1", inputs={"wheel": {"required": True}}),
    "x/c@v1": mk_spec("x/c@v1", inputs={"path": {"required": True}}),
}


@pytest.mark.parametrize("config", [{}, {"unrelated": 1}])
def test_FLOW001_and_CONF001_accept_inputs_fed_by_another_job(config):
    recipe = (
        "on: push\njobs:\n  build:\n    steps: [{id: p, uses: x/a@v1}]\n"
        "  test:\n    steps:\n      - {id: t, uses: x/b@v1}\n"
        "      - {id: u, uses: x/c@v1, bind: {path: other}}\n"
    )
    g = mk_graph(recipe, _XJOB_SPECS)
    assert _only("FLOW001", g, config) == [] and _only("CONF001", g, config) == []


def test_FLOW001_and_CONF001_still_flag_an_input_no_job_produces():
    recipe = (
        "on: push\njobs:\n  build:\n    steps: [{id: p, uses: x/a@v1}]\n"
        "  test:\n    steps: [{id: u, uses: x/c@v1}]\n"  # needs `path`: nobody has it
    )
    g = mk_graph(recipe, _XJOB_SPECS)
    assert len(_only("FLOW001", g)) == 1 and len(_only("CONF001", g)) == 1


def test_validation_and_compiler_agree_on_which_required_inputs_are_sourced():
    from reci.compiler import compile_recipe
    from reci.recipe import parse_recipe_string

    recipes = {
        "cross-job": (
            "on: push\njobs:\n  build:\n    steps: [{id: p, uses: x/a@v1}]\n"
            "  test:\n    steps: [{id: t, uses: x/b@v1}]\n"
        ),
        "unsourced": "on: push\njobs:\n  j:\n    steps: [{id: t, uses: x/b@v1}]\n",
        "same-job-later": (
            "on: push\njobs:\n  j:\n    steps:\n      - {id: t, uses: x/b@v1}\n"
            "      - {id: p, uses: x/a@v1}\n"
        ),
    }
    for name, text in recipes.items():
        recipe = parse_recipe_string(text)
        wf = compile_recipe(recipe, _XJOB_SPECS)
        wired = any(
            "wheel" in step.get("with", {})
            for job in wf["jobs"].values()
            for step in job["steps"]
            if step["id"] == "t"
        )
        flagged = bool(_only("FLOW001", mk_graph(text, _XJOB_SPECS)))
        assert flagged != wired, name


def test_FLOW001_looks_at_every_step_of_a_producer_job_not_just_one():
    specs = {
        **_XJOB_SPECS,
        "x/d@v1": mk_spec("x/d@v1", outputs=["unrelated"]),
    }
    for order in ("x/a@v1, x/d@v1", "x/d@v1, x/a@v1"):  # producer first or last
        steps = ", ".join(f"{{id: s{i}, uses: {u}}}" for i, u in enumerate(order.split(", ")))
        recipe = (
            f"on: push\njobs:\n  build:\n    steps: [{steps}]\n"
            "  test:\n    steps: [{id: t, uses: x/b@v1}]\n"
        )
        assert _only("FLOW001", mk_graph(recipe, specs)) == [], order


def test_FLOW001_bind_replaces_the_name_searched_for():
    # `wheel` is produced elsewhere, but the input is bound to a name nobody makes
    recipe = (
        "on: push\njobs:\n  build:\n    steps: [{id: p, uses: x/a@v1}]\n"
        "  test:\n    steps: [{id: t, uses: x/b@v1, bind: {wheel: nothing}}]\n"
    )
    g = mk_graph(recipe, _XJOB_SPECS)
    assert len(_only("FLOW001", g)) == 1 and len(_only("CONF001", g)) == 1


def test_CONF004_sees_a_config_ref_in_continue_on_error():
    recipe = (
        "on: push\njobs:\n  j:\n    continue-on-error: ${{ fromJSON(config.lenient) }}\n"
        "    steps: [{run: a}]\n"
    )
    (f,) = _only("CONF004", mk_graph(recipe), {"other": 1})
    assert "config.lenient" in f.message and f.location == "j"


def test_CONF005_reports_unusable_keys_and_unexportable_values():
    g = mk_graph(_steps("{id: r, run: e}"))
    found = _only("CONF005", g, {"a.b": 1, "ok": "x\ry", "fine": "x\ty", "lst": ["\r"]})
    assert sorted(f.message.split("'")[1] for f in found) == ["a.b", "ok"]
    assert all(f.severity is Severity.ERROR and f.location == "config" for f in found)


@pytest.mark.parametrize(
    "ref",
    [
        "steps['p'].outputs.v",
        "steps.p.outputs['v']",
        "steps.P.outputs.V",
    ],
)
def test_FLOW004_counts_bracket_and_case_variants_of_a_reference(ref):
    specs = {"x/p@v1": mk_spec("x/p@v1", outputs=["v"])}
    run = json.dumps(f"echo ${{{{ {ref} }}}}")
    recipe = _steps("{id: p, uses: x/p@v1}", f"{{id: r, run: {run}}}")
    assert _only("FLOW004", mk_graph(recipe, specs)) == []


def test_FLOW004_counts_a_reference_in_a_step_name():
    specs = {"x/p@v1": mk_spec("x/p@v1", outputs=["v"])}
    recipe = _steps(
        "{id: p, uses: x/p@v1}", "{id: r, name: 'n ${{ steps.p.outputs.v }}', run: e}"
    )
    assert _only("FLOW004", mk_graph(recipe, specs)) == []


@pytest.mark.parametrize(
    "extra",
    [
        "    if: ${{ steps.p.outputs.v }}\n",  # job-level `steps` never resolves
        "    continue-on-error: ${{ steps.p.outputs.v }}\n",
        "    env: {E: '${{ steps.p.outputs.v }}'}\n",
    ],
)
def test_FLOW004_ignores_job_level_references_and_dict_keys(extra):
    specs = {"x/p@v1": mk_spec("x/p@v1", outputs=["v"])}
    recipe = (
        f"on: push\njobs:\n  a:\n{extra}    steps: [{{id: p, uses: x/p@v1}}]\n"
    )
    assert len(_only("FLOW004", mk_graph(recipe, specs))) == 1
    keyed = _steps(
        "{id: p, uses: x/p@v1}", "{id: r, run: e, env: {'${{ steps.p.outputs.v }}': 1}}"
    )
    assert len(_only("FLOW004", mk_graph(keyed, specs))) == 1


def test_FLOW004_counts_a_declared_job_output_and_step_extra_keys_as_consumption():
    specs = {"x/p@v1": mk_spec("x/p@v1", outputs=["v", "w"])}
    recipe = (
        "on: push\njobs:\n  j:\n    outputs: {o: '${{ steps.p.outputs.v }}'}\n"
        "    steps:\n      - {id: p, uses: x/p@v1}\n"
        "      - {run: x, working-directory: '${{ steps.p.outputs.w }}'}\n"
    )
    assert _only("FLOW004", mk_graph(recipe, specs)) == []


_LOOP_RECIPE = (
    "on: push\njobs:\n  a:\n    steps: [{id: s, uses: x/a@v1}]\n"
    "  b:\n    steps: [{id: t, uses: x/b@v1}]\n"
)


def test_DAG005_config_supplying_an_input_breaks_the_cycle_in_validation_too():
    g = mk_graph(_LOOP_RECIPE, _LOOP_SPECS)
    assert len(_only("DAG005", g)) == 1
    assert _only("DAG005", g, {"w": "from-config"}) == []


def test_DAG005_reports_a_data_flow_cycle_beside_an_explicit_needs_cycle():
    recipe = (
        "on: push\njobs:\n  e1:\n    needs: e2\n    steps: [{run: x}]\n"
        "  e2:\n    needs: e1\n    steps: [{run: x}]\n"
        "  a:\n    steps: [{id: s, uses: x/a@v1}]\n"
        "  b:\n    steps: [{id: t, uses: x/b@v1}]\n"
    )
    g = mk_graph(recipe, _LOOP_SPECS)
    assert len(_only("DAG001", g)) == 1
    (f,) = _only("DAG005", g)
    assert "e1" not in f.message and "'b.t' reads 'v' from 'a.s'" in f.message


def test_DAG005_names_only_the_other_producers_that_avoid_the_cycle():
    specs = {
        **_LOOP_SPECS,
        "x/c@v1": mk_spec("x/c@v1", outputs=["v"]),
    }
    recipe = _LOOP_RECIPE + "  c:\n    steps: [{id: u, uses: x/c@v1}]\n"
    (f,) = _only("DAG005", mk_graph(recipe, specs))
    assert "also produced by job 'c'" in f.suggestion and "bind:" in f.suggestion


# -- cross-job producer choice: FLOW002, FLOW006 --------------------------------

_PRODUCERS = {
    "x/p@v1": mk_spec("x/p@v1", outputs=["v"]),
    "x/c@v1": mk_spec("x/c@v1", inputs={"v": {"required": True}}),
}


def _two_producers(extra_first_job=""):
    return (
        f"on: push\njobs:\n  p1:\n{extra_first_job}    steps: [{{id: a, uses: x/p@v1}}]\n"
        "  p2:\n    steps: [{id: b, uses: x/p@v1}]\n"
        "  c:\n    steps: [{id: z, uses: x/c@v1}]\n"
    )


def test_FLOW002_warns_when_several_jobs_produce_what_a_job_consumes():
    (f,) = _only("FLOW002", mk_graph(_two_producers(), _PRODUCERS))
    assert f.severity is Severity.WARNING and f.location == "c.z"
    assert "p1, p2" in f.message and "Using the first, 'p1'" in f.message
    assert "bind:" in f.suggestion
    one = _two_producers().replace("  p2:\n    steps: [{id: b, uses: x/p@v1}]\n", "")
    assert _only("FLOW002", mk_graph(one, _PRODUCERS)) == []


def test_FLOW002_stays_quiet_when_the_input_is_given_explicitly():
    recipe = _two_producers().replace(
        "{id: z, uses: x/c@v1}", "{id: z, uses: x/c@v1, with: {v: 1}}"
    )
    assert _only("FLOW002", mk_graph(recipe, _PRODUCERS)) == []


def test_FLOW006_warns_about_a_matrix_producer():
    recipe = _two_producers().replace(
        "  p2:\n    steps: [{id: b, uses: x/p@v1}]\n", ""
    ).replace(
        "  p1:\n", "  p1:\n    strategy: {matrix: {os: [a, b]}}\n"
    )
    (f,) = _only("FLOW006", mk_graph(recipe, _PRODUCERS))
    assert f.severity is Severity.WARNING and "whichever leg finishes last" in f.message
    assert f.location == "p1.a" and f.suggestion


def test_FLOW006_warns_about_a_conditional_producer_and_not_about_a_plain_one():
    plain = _two_producers().replace("  p2:\n    steps: [{id: b, uses: x/p@v1}]\n", "")
    assert _only("FLOW006", mk_graph(plain, _PRODUCERS)) == []
    conditional = plain.replace("  p1:\n", "  p1:\n    if: github.ref == 'refs/heads/main'\n")
    (f,) = _only("FLOW006", mk_graph(conditional, _PRODUCERS))
    assert "has an if:" in f.message and "skipped" in f.message


def test_FLOW006_ignores_a_matrix_job_nobody_reads_from():
    recipe = (
        "on: push\njobs:\n  p1:\n    strategy: {matrix: {os: [a, b]}}\n"
        "    steps: [{id: a, uses: x/p@v1}]\n"
    )
    assert _only("FLOW006", mk_graph(recipe, _PRODUCERS)) == []


def test_DAG005_does_not_suggest_a_producer_that_depends_on_the_consumer():
    specs = {**_LOOP_SPECS, "x/c@v1": mk_spec("x/c@v1", outputs=["v"])}
    recipe = _LOOP_RECIPE + (
        "  c:\n    needs: b\n    steps: [{id: u, uses: x/c@v1}]\n"
    )  # c also produces v, but needs b, the consumer of v
    (f,) = _only("DAG005", mk_graph(recipe, specs))
    assert "also produced" not in f.suggestion


def test_DAG005_leaves_an_explicit_needs_cycle_to_DAG001():
    specs = {
        "x/p@v1": mk_spec("x/p@v1", outputs=["v"]),
        "x/c@v1": mk_spec("x/c@v1", inputs={"v": {"required": True}}),
    }
    recipe = (
        "on: push\njobs:\n  a:\n    needs: b\n    steps: [{id: s, uses: x/p@v1}]\n"
        "  b:\n    needs: a\n    steps: [{id: t, uses: x/c@v1}]\n"
    )
    g = mk_graph(recipe, specs)
    assert len(_only("DAG001", g)) == 1 and _only("DAG005", g) == []


def test_FLOW006_stays_quiet_when_the_skip_cannot_reach_the_consumer():
    plain = _two_producers().replace("  p2:\n    steps: [{id: b, uses: x/p@v1}]\n", "")
    guarded = plain.replace("  p1:\n", "  p1:\n    if: github.ref == 'x'\n")
    resilient = guarded.replace("  c:\n", "  c:\n    if: ${{ always() }}\n")
    assert _only("FLOW006", mk_graph(resilient, _PRODUCERS)) == []
    never_skipped = plain.replace("  p1:\n", "  p1:\n    if: always()\n")
    assert _only("FLOW006", mk_graph(never_skipped, _PRODUCERS)) == []


# -- FLOW004: which references count --------------------------------------------

_P = {"x/p@v1": mk_spec("x/p@v1", outputs=["wheel-path"])}


def _flow004(*steps):
    return _only("FLOW004", mk_graph(_steps("{id: p, uses: x/p@v1}", *steps), _P))


@pytest.mark.parametrize(
    "step",
    [
        "{id: r, run: 'echo Steps.P.Outputs.Wheel-Path'}",  # not inside ${{ }}
        "{id: r, run: 'echo ${{ steps.p.outputs.wheel_path }}'}",  # `_` is not `-`
        "{id: r, run: \"echo ${{ 'steps.p.outputs.wheel-path' }}\"}",  # a string literal
        "{id: r, run: 'echo ${{ steps.q.outputs.wheel-path }}'}",  # another step
    ],
)
def test_FLOW004_does_not_count_text_that_is_not_a_reference(step):
    assert len(_flow004(step)) == 1


@pytest.mark.parametrize(
    "step",
    [
        "{id: r, run: 'echo ${{ Steps.P.Outputs.Wheel-Path }}'}",
        "{id: r, run: \"echo ${{ steps.p['outputs'].wheel-path }}\"}",
        "{id: r, run: x, if: steps.p.outputs.wheel-path}",  # `if:` needs no ${{ }}
    ],
)
def test_FLOW004_counts_case_variants_and_a_bare_if(step):
    assert _flow004(step) == []


def test_FLOW004_does_not_count_a_reference_before_or_inside_the_producing_step():
    before = _steps(
        "{id: r, run: 'echo ${{ steps.p.outputs.wheel-path }}'}",
        "{id: p, uses: x/p@v1}",
    )
    assert len(_only("FLOW004", mk_graph(before, _P))) == 1
    inside = _steps(
        "{id: p, uses: x/p@v1, env: {E: '${{ steps.p.outputs.wheel-path }}'}}"
    )
    assert len(_only("FLOW004", mk_graph(inside, _P))) == 1


# -- FLOW007: references that resolve to nothing --------------------------------


def _flow007(recipe, specs=None):
    return _only("FLOW007", mk_graph(recipe, _P if specs is None else specs))


def test_FLOW007_step_output_references_that_are_empty():
    ghost = _steps("{id: r, run: 'echo ${{ steps.nope.outputs.v }}'}")
    (f,) = _flow007(ghost)
    assert "no step 'nope'" in f.message and f.location == "j.r"
    early = _steps(
        "{id: r, run: 'echo ${{ steps.p.outputs.wheel-path }}'}",
        "{id: p, uses: x/p@v1}",
    )
    (f,) = _flow007(early)
    assert "has not run at that point" in f.message
    typo = _steps(
        "{id: p, uses: x/p@v1}", "{id: r, run: 'echo ${{ steps.p.outputs.wheel_path }}'}"
    )
    (f,) = _flow007(typo)
    assert "no output 'wheel_path'" in f.message and "did you mean 'wheel-path'" in f.message


def test_FLOW007_accepts_valid_step_references_and_undeclared_run_outputs():
    ok = _steps(
        "{id: p, uses: x/p@v1}",
        "{id: q, run: x, outputs: [anything]}",
        "{id: r, run: 'echo ${{ steps.P.outputs.Wheel-Path }} ${{ steps.q.outputs.zzz }}'}",
    )
    assert _flow007(ok) == []


def test_FLOW007_needs_references():
    base = (
        "on: push\njobs:\n  a:\n    steps: [{id: p, uses: x/p@v1}]\n"
        "  b:\n    needs: a\n    steps: [{id: r, run: 'echo ${{ needs.%s.outputs.%s }}'}]\n"
    )
    (f,) = _flow007(base % ("a", "v"))
    assert "declares no such output" in f.message and f.location == "b"
    (f,) = _flow007(base % ("zz", "v"))
    assert "'zz' is not a job it needs" in f.message
    declared = base.replace(
        "steps: [{id: p, uses: x/p@v1}]",
        "outputs: {v: x}\n    steps: [{id: p, uses: x/p@v1}]",
        1,
    )
    assert _flow007(declared % ("a", "v")) == []
    assert _flow007(base % ("setup", "anything")) == []  # config is CONF004's
    not_needed = base.replace("needs: a\n", "")
    (f,) = _flow007(not_needed % ("a", "v"))
    assert "not a job it needs" in f.message


def test_FLOW007_accepts_an_output_the_compiler_forwards():
    specs = {
        "x/p@v1": mk_spec("x/p@v1", outputs=["v"]),
        "x/c@v1": mk_spec("x/c@v1", inputs={"v": {}}),
    }
    recipe = (
        "on: push\njobs:\n  a:\n    steps: [{id: p, uses: x/p@v1}]\n"
        "  b:\n    steps:\n      - {id: c, uses: x/c@v1}\n"
        "      - {id: r, run: 'echo ${{ needs.a.outputs.v }}'}\n"
    )  # b reads v through c, so the compiler forwards it and adds needs: a
    assert _flow007(recipe, specs) == []


def test_FLOW007_only_a_composite_action_must_declare_every_output():
    from reci.action_spec import parse_action_spec

    def spec(using):
        return {
            "x/n@v1": parse_action_spec(
                "x/n@v1",
                action_yml_data={
                    "runs": {"using": using},
                    "outputs": {"declared": {}},
                },
            )
        }

    recipe = _steps(
        "{id: p, uses: x/n@v1}", "{id: r, run: 'echo ${{ steps.p.outputs.dyn }}'}"
    )
    assert _flow007(recipe, spec("node20")) == []  # may set undeclared outputs
    (f,) = _flow007(recipe, spec("composite"))
    assert "declares no output 'dyn'" in f.message


def test_FLOW007_reports_a_repeated_reference_once_and_tolerates_odd_output_keys():
    twice = _steps(
        "{id: r, run: 'echo ${{ steps.nope.outputs.a }} ${{ steps.nope.outputs.a }}'}"
    )
    assert len(_flow007(twice)) == 1
    recipe = (
        "on: push\njobs:\n  a:\n    outputs: {1: x}\n    steps: [{run: x}]\n"
        "  b:\n    needs: a\n    steps:\n"
        "      - {run: 'echo ${{ needs.a.outputs.v }}'}\n"
        "      - {run: 'echo ${{ needs.a.outputs.v }}'}\n"
    )
    assert len(_flow007(recipe)) == 1
