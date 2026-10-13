"""Recipe parsing and YAML I/O: structural errors, id derivation, ``on:`` handling."""

import pytest

from reci.recipe import RecipeParseError, parse_recipe, parse_recipe_string
from reci.yaml_gen import dump_workflow, load_yaml_string


def test_parses_jobs_steps_and_defaults():
    r = parse_recipe_string(
        """\
name: demo
on: [push]
env: {A: "1"}
jobs:
  build:
    needs: setup
    steps:
      - uses: actions/checkout@v4
      - run: make
        outputs: result
        env: {X: y}
"""
    )
    job = r.jobs["build"]
    assert r.name == "demo" and r.on == ["push"] and r.env == {"A": "1"}
    assert job.needs == ["setup"]  # a bare string is promoted to a list
    assert job.runs_on == "ubuntu-latest"
    assert [s.id for s in job.steps] == ["checkout", "step_1"]
    assert job.steps[1].outputs == ["result"] and job.steps[1].env == {"X": "y"}


def test_with_values_are_coerced_to_strings():
    r = parse_recipe_string(
        "on: push\njobs:\n  j:\n    steps:\n      - uses: a/b@v1\n        with: {n: 3}\n"
    )
    assert r.jobs["j"].steps[0].with_ == {"n": "3"}


def test_yaml_booleans_in_with_are_rendered_lowercase():
    r = parse_recipe_string(
        "on: push\njobs:\n  j:\n    steps:\n      - uses: a/b@v1\n        with: {flag: true}\n"
    )
    assert r.jobs["j"].steps[0].with_ == {"flag": "true"}


def test_bind_survives_step_id_deduplication():
    r = parse_recipe_string(
        "on: push\njobs:\n  j:\n    steps:\n      - uses: a/t@v1\n      - uses: a/t@v1\n"
        "        bind: {x: y}\n        env: {E: '1'}\n        outputs: [o]\n        name: n\n"
        "        if: ${{ always() }}\n        with: {k: v}\n"
    )
    dup = r.jobs["j"].steps[1]
    assert dup.id == "t_1"
    assert (dup.bind, dup.env, dup.outputs, dup.name, dup.if_, dup.with_) == (
        {"x": "y"},
        {"E": "1"},
        ["o"],
        "n",
        "${{ always() }}",
        {"k": "v"},
    )


@pytest.mark.parametrize(
    "step, msg",
    [
        ("- uses: a/b@v1\n        run: echo", "both 'uses' and 'run'"),
        ("- name: nothing", "neither 'uses' nor 'run'"),
    ],
)
def test_invalid_steps_are_rejected(step, msg):
    with pytest.raises(RecipeParseError, match=msg):
        parse_recipe_string(f"on: push\njobs:\n  j:\n    steps:\n      {step}\n")


def test_job_without_steps_and_recipe_without_jobs_are_rejected():
    with pytest.raises(RecipeParseError, match="no steps"):
        parse_recipe_string("on: push\njobs:\n  j:\n    runs-on: x\n")
    with pytest.raises(RecipeParseError, match="no jobs"):
        parse_recipe_string("name: x\non: push\n")
    with pytest.raises(RecipeParseError, match="not a YAML mapping"):
        parse_recipe_string("- just\n- a list\n")


def test_duplicate_auto_ids_get_numeric_suffixes_but_explicit_ids_are_kept():
    r = parse_recipe_string(
        """\
on: push
jobs:
  j:
    steps:
      - uses: a/tool@v1
      - uses: a/tool@v2
      - uses: b/tool@v1
      - uses: a/other@v1
        id: mine
"""
    )
    assert [s.id for s in r.jobs["j"].steps] == ["tool", "tool_1", "tool_2", "mine"]


def test_auto_id_normalizes_hyphens():
    r = parse_recipe_string(
        "on: push\njobs:\n  j:\n    steps:\n      - uses: o/r/actions/run-tests@v1\n"
    )
    assert r.jobs["j"].steps[0].id == "run_tests"


def test_parse_recipe_from_file_matches_string(tmp_path):
    text = "name: f\non: push\njobs:\n  j:\n    steps:\n      - run: echo\n"
    p = tmp_path / "r.yml"
    p.write_text(text)
    assert parse_recipe(str(p)) == parse_recipe_string(text)


def test_dump_workflow_quotes_expressions_and_uses_block_scalars():
    out = dump_workflow(
        {
            "on": ["push"],
            "jobs": {
                "j": {
                    "steps": [
                        {"run": "a\nb"},
                        {"with": {"x": "${{ needs.setup.outputs.x }}"}},
                    ]
                }
            },
        }
    )
    assert "run: |-\n" in out or "run: |\n" in out  # literal block, not escaped \n
    assert "x: '${{ needs.setup.outputs.x }}'" in out
    assert "\non:\n" in "\n" + out  # `on` stays a plain key (YAML 1.2, not `true`)
    assert load_yaml_string(out)["on"] == ["push"]


def test_dump_workflow_writes_to_a_stream(tmp_path):
    p = tmp_path / "w.yml"
    with open(p, "w") as f:
        assert dump_workflow({"name": "n"}, stream=f) is None
    assert p.read_text() == "name: n\n"


def test_workflow_defaults_are_parsed():
    r = parse_recipe_string(
        "on: push\ndefaults: {run: {shell: bash}}\njobs:\n  j:\n    steps: [{run: echo}]\n"
    )
    assert r.defaults == {"run": {"shell": "bash"}}


def test_yaml_scalars_in_with_and_env_are_rendered_as_github_sees_them():
    r = parse_recipe_string(
        "on: push\nenv: {W: true}\njobs:\n  j:\n    env: {J: false}\n    steps:\n"
        "      - uses: a/b@v1\n        env: {E: true, N: 1.5, Z: }\n"
        "        with: {on: true, off: false, empty: , n: 3}\n"
    )
    step = r.jobs["j"].steps[0]
    assert step.with_ == {"on": "true", "off": "false", "empty": "", "n": "3"}
    assert step.env == {"E": "true", "N": "1.5", "Z": ""}
    assert r.jobs["j"].env == {"J": "false"} and r.env == {"W": "true"}


def test_boolean_env_and_with_compile_to_valid_lowercase_workflow():
    from reci.compiler import compile_recipe
    from reci.tests._helpers import assert_valid_workflow, mk_spec

    recipe = parse_recipe_string(
        "on: push\njobs:\n  j:\n    env: {A: true}\n    steps:\n"
        "      - {id: s, uses: x/s@v1, env: {B: false}, with: {flag: true}}\n"
    )
    wf = compile_recipe(recipe, {"x/s@v1": mk_spec("x/s@v1")})
    assert_valid_workflow(wf)
    job = wf["jobs"]["j"]
    assert job["env"] == {"A": "true"}
    assert job["steps"][0]["env"] == {"B": "false"}
    assert job["steps"][0]["with"] == {"flag": "true"}


def test_anchored_booleans_are_still_booleans():
    r = parse_recipe_string(
        "on: push\njobs:\n  j:\n    env: {A: &x true, B: *x, C: &y false}\n"
        "    steps:\n      - uses: a/b@v1\n        with: {p: &z true, q: *z}\n"
    )
    assert r.jobs["j"].env == {"A": "true", "B": "true", "C": "false"}
    assert r.jobs["j"].steps[0].with_ == {"p": "true", "q": "true"}


def test_strings_pass_through_unchanged_and_non_scalars_are_rejected():
    r = parse_recipe_string(
        "on: push\njobs:\n  j:\n    steps:\n      - uses: a/b@v1\n"
        "        with: {a: Hello, b: 'True', c: 'null', d: '', e: 'a: b'}\n"
    )
    assert r.jobs["j"].steps[0].with_ == {
        "a": "Hello",
        "b": "True",
        "c": "null",
        "d": "",
        "e": "a: b",
    }
    for field, value in [("with", "[a, b]"), ("env", "{k: v}")]:
        with pytest.raises(RecipeParseError, match="must be a scalar"):
            parse_recipe_string(
                "on: push\njobs:\n  j:\n    steps:\n      - uses: a/b@v1\n"
                f"        {field}: {{x: {value}}}\n"
            )


def test_boolean_if_is_expression_text_not_dropped_or_crashing():
    r = parse_recipe_string(
        "on: push\njobs:\n  j:\n    if: false\n    steps:\n"
        "      - {run: a, if: false}\n      - {run: b, if: true}\n"
        "      - {run: c, if: always()}\n      - {run: d}\n"
    )
    assert r.jobs["j"].if_ == "false"
    assert [st.if_ for st in r.jobs["j"].steps] == ["false", "true", "always()", None]


def test_continue_on_error_keeps_booleans_and_expressions():
    def coe(value):
        text = f"on: push\njobs:\n  j:\n    continue-on-error: {value}\n    steps: [{{run: a}}]\n"
        return parse_recipe_string(text).jobs["j"].continue_on_error

    assert coe("true") is True and coe("false") is False and coe("'true'") is True
    assert coe("'${{ matrix.exp }}'") == "${{ matrix.exp }}"
