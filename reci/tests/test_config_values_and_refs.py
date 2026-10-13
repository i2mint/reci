"""Config values (export text, spelling, refusal) and config references in recipes."""

import datetime

import pytest
import tomlkit

from reci.adapters import get_adapter
from reci.compiler import CompilationError, compile_recipe
from reci.recipe import parse_recipe_string
from reci.recipe_checks import serialize_config_value
from reci.tests._helpers import assert_valid_workflow, mk_graph

ONE_JOB = "on: push\njobs:\n  j:\n    steps: [{run: echo}]\n"


def _compile(recipe_yaml, config=None):
    wf = compile_recipe(parse_recipe_string(recipe_yaml), {}, config=config)
    assert_valid_workflow(wf)
    return wf


def _setup_script(wf):
    return wf["jobs"]["setup"]["steps"][0]["run"]


def test_dates_inside_lists_and_dicts_are_exported_as_iso_text():
    config = {
        "dates": [datetime.date(2024, 1, 2)],
        "nested": {"at": datetime.datetime(2024, 1, 2, 3, 4)},
        "day": datetime.date(2024, 1, 2),
    }
    script = _setup_script(_compile(ONE_JOB, config))
    assert '["2024-01-02"]' in script and '"at": "2024-01-02T03:04:00"' in script
    assert "day 2024-01-02" in script.replace("'", "").replace("=", " ")


def test_tuples_export_as_json_lists():
    assert serialize_config_value((1, "a")) == '[1, "a"]'


@pytest.mark.parametrize("value", [None, b"x", {1, 2}, object()])
def test_values_with_no_faithful_text_are_refused(value):
    with pytest.raises(CompilationError, match=r"\[CONF005\].*config key 'k'"):
        _compile(ONE_JOB, {"k": value})


def test_nested_none_is_json_null_but_nested_bytes_are_refused():
    assert serialize_config_value({"a": None}) == '{"a": null}'
    with pytest.raises(CompilationError, match="CONF005"):
        _compile(ONE_JOB, {"k": [b"x"]})


def test_toml_numbers_keep_their_spelling():
    doc = tomlkit.parse("python-version = 3.10\nhexed = 0x1F\nplain = 3.9\ncount = 3\n")
    config = {k: doc[k] for k in doc}
    assert serialize_config_value(config["python-version"]) == "3.10"
    assert serialize_config_value(config["hexed"]) == "31"
    assert serialize_config_value(config["plain"]) == "3.9"
    assert serialize_config_value(config["count"]) == "3"


def test_yaml_numbers_keep_their_spelling(tmp_path):
    path = tmp_path / ".ci.yml"
    path.write_text("python-version: 3.10\nn: 7\nflag: true\n")
    config = get_adapter("yaml").read(str(path))
    script = _setup_script(_compile(ONE_JOB, config))
    assert "python-version 3.10" in script.replace("'", "").replace("=", " ")
    assert serialize_config_value(config["flag"]) == "true"


def test_pyproject_toml_float_reaches_the_workflow_as_written(tmp_path):
    path = tmp_path / "pyproject.toml"
    path.write_text("[tool.ci]\npython-version = 3.10\n")
    config = get_adapter("pyproject").read(str(path))
    assert "printf '%s=%s\\n' python-version 3.10\n" in _setup_script(
        _compile(ONE_JOB, config)
    )


def _problems(recipe_yaml, config):
    with pytest.raises(CompilationError) as e:
        _compile(recipe_yaml, config)
    return str(e.value)


@pytest.mark.parametrize(
    "expr, shown",
    [
        ("${{ config.x.y }}", "config.x.y"),
        ("${{ config.x[0] }}", "config.x["),
        ("${{ config['x'] }}", "config["),
        ("${{ toJSON(config) }}", "'config'"),
        ("${{ config.* }}", "config.*"),
    ],
)
def test_CONF004_reports_config_references_reci_cannot_rewrite(expr, shown):
    recipe = f"on: push\njobs:\n  j:\n    steps: [{{run: echo, name: \"{expr}\"}}]\n"
    message = _problems(recipe, {"x": "1"})
    assert "[CONF004]" in message and "cannot rewrite" in message and shown in message


def test_unsupported_config_forms_are_ignored_where_they_are_not_expressions():
    recipe = (
        "on: push\njobs:\n  j:\n    steps:\n"
        "      - run: cat config.json && echo '${{ github.event.config.a }}'\n"
        "        name: \"${{ 'config.x.y' }}\"\n"
    )
    _compile(recipe, {"x": "1"})


def test_bare_if_condition_gets_config_refs_rewritten():
    recipe = (
        "on: push\njobs:\n  j:\n    if: config.flag == 'true'\n    steps:\n"
        "      - {run: a, if: \"config.flag == 'true' && always()\"}\n"
        "      - {run: b, if: always()}\n"
    )
    job = _compile(recipe, {"flag": True})["jobs"]["j"]
    assert job["if"] == "needs.setup.outputs.flag == 'true'"
    assert job["steps"][0]["if"] == "needs.setup.outputs.flag == 'true' && always()"
    assert job["steps"][1]["if"] == "always()"


def test_bare_if_condition_with_an_unknown_config_key_is_refused():
    recipe = "on: push\njobs:\n  j:\n    steps: [{run: a, if: config.nope}]\n"
    assert "config.nope, which is not a config key" in _problems(recipe, {"x": 1})


def test_config_refs_match_keys_case_insensitively():
    recipe = "on: push\njobs:\n  j:\n    steps: [{run: a, name: '${{ config.Python }}'}]\n"
    wf = _compile(recipe, {"python": "3.12"})
    assert wf["jobs"]["j"]["steps"][0]["name"] == "${{ needs.setup.outputs.Python }}"
    assert "not a config key" in _problems(recipe, {"other": "x"})


def test_validation_reports_the_same_problems_as_the_compiler():
    graph = mk_graph(
        "on: push\njobs:\n  j:\n    steps: [{run: a, name: '${{ config.x.y }}'}]\n"
    )
    findings = graph.validate({"x": "1"}).findings
    assert any(f.rule_id == "CONF004" and "config.x.y" in f.message for f in findings)
