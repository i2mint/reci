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
