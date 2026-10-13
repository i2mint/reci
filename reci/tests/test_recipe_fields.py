"""Recipe keys reci does not model reach the workflow; step ids and matrix numbers stay valid."""

import pytest

from reci.compiler import CompilationError, compile_recipe
from reci.recipe import RecipeParseError, parse_recipe_string
from reci.tests._helpers import assert_valid_workflow, mk_spec


def _compile(recipe_yaml, specs=None, config=None):
    """Compile, and require the result to pass actionlint (skipped if absent)."""
    wf = compile_recipe(parse_recipe_string(recipe_yaml), specs or {}, config=config)
    assert_valid_workflow(wf)
    return wf


def test_step_keys_without_recipe_meaning_are_emitted():
    wf = _compile(
        "on: push\njobs:\n  j:\n    steps:\n"
        "      - {run: make, timeout-minutes: 5, continue-on-error: true,\n"
        "         shell: bash, working-directory: sub}\n"
    )
    step = wf["jobs"]["j"]["steps"][0]
    assert step["timeout-minutes"] == 5 and step["continue-on-error"] is True
    assert step["shell"] == "bash" and step["working-directory"] == "sub"


def test_step_continue_on_error_expression_gets_config_refs_rewritten():
    wf = _compile(
        "on: push\njobs:\n  j:\n    steps:\n"
        "      - {run: x, continue-on-error: '${{ fromJSON(config.lenient) }}'}\n",
        config={"lenient": True},
    )
    step = wf["jobs"]["j"]["steps"][0]
    assert step["continue-on-error"] == "${{ fromJSON(needs.setup.outputs.lenient) }}"


@pytest.mark.parametrize("where", ["job", "step"])
def test_continue_on_error_that_is_neither_boolean_nor_expression_is_refused(where):
    job = (
        "    continue-on-error: maybe\n    steps: [{run: x}]\n"
        if where == "job"
        else "    steps: [{run: x, continue-on-error: maybe}]\n"
    )
    with pytest.raises(RecipeParseError, match="continue-on-error"):
        parse_recipe_string("on: push\njobs:\n  j:\n" + job)


def test_job_keys_without_recipe_meaning_are_emitted():
    wf = _compile(
        "on: push\njobs:\n  j:\n    name: The job\n    timeout-minutes: 20\n"
        "    concurrency: {group: g, cancel-in-progress: true}\n"
        "    environment: prod\n    steps: [{run: x}]\n"
    )
    job = wf["jobs"]["j"]
    assert job["name"] == "The job" and job["timeout-minutes"] == 20
    assert job["concurrency"] == {"group": "g", "cancel-in-progress": True}
    assert job["environment"] == "prod"


def test_extra_keys_get_config_refs_rewritten_and_checked():
    recipe = (
        "on: push\njobs:\n  j:\n    timeout-minutes: ${{ fromJSON(config.t) }}\n"
        "    steps: [{run: x, working-directory: '${{ config.d }}'}]\n"
    )
    wf = _compile(recipe, config={"t": 5, "d": "sub"})
    job = wf["jobs"]["j"]
    assert job["timeout-minutes"] == "${{ fromJSON(needs.setup.outputs.t) }}"
    assert job["steps"][0]["working-directory"] == "${{ needs.setup.outputs.d }}"
    with pytest.raises(CompilationError, match="config.d, which is not a config key"):
        _compile(recipe, config={"t": 5})


def test_declared_job_outputs_are_kept_next_to_forwarded_ones():
    specs = {
        "x/a@v1": mk_spec("x/a@v1", outputs=["v"]),
        "x/b@v1": mk_spec("x/b@v1", inputs={"v": {"required": True}}),
    }
    recipe = (
        "on: push\njobs:\n  p:\n    outputs: {mine: '${{ steps.a.outputs.v }}'}\n"
        "    steps: [{uses: x/a@v1, id: a}]\n"
        "  c:\n    steps: [{uses: x/b@v1}]\n"
    )
    outputs = _compile(recipe, specs)["jobs"]["p"]["outputs"]
    assert set(outputs) == {"mine", "v"}
    clash = recipe.replace("{mine:", "{v:")
    with pytest.raises(CompilationError, match="rename one"):
        _compile(clash, specs)


def test_workflow_defaults_and_other_top_level_keys_are_emitted():
    wf = _compile(
        "name: W\non: push\ndefaults: {run: {shell: bash}}\n"
        "concurrency: {group: g}\npermissions: {contents: read}\n"
        "jobs:\n  j:\n    steps: [{run: x}]\n"
    )
    assert wf["defaults"] == {"run": {"shell": "bash"}}
    assert wf["concurrency"] == {"group": "g"}
    assert wf["permissions"] == {"contents": "read"}


@pytest.mark.parametrize(
    "head",
    [
        "name: 'W ${{ config.k }}'\non: push\n",
        "on: push\ndefaults: {run: {working-directory: '${{ config.k }}'}}\n",
        "on: push\nconcurrency: {group: '${{ config.k }}'}\n",
    ],
)
def test_config_ref_in_workflow_level_fields_is_refused(head):
    with pytest.raises(CompilationError, match="no 'needs' context"):
        _compile(head + "jobs:\n  j:\n    steps: [{run: x}]\n", config={"k": "v"})


def test_matrix_numbers_keep_their_spelling():
    wf = _compile(
        "on: push\njobs:\n  j:\n    strategy:\n      matrix:\n"
        "        python-version: [3.10, 3.9, '3.11']\n        n: [1, 2]\n"
        "        include: [{python-version: 3.10, extra: 1.20}]\n"
        "    steps: [{run: x}]\n"
    )
    matrix = wf["jobs"]["j"]["strategy"]["matrix"]
    assert matrix["python-version"] == ["3.10", 3.9, "3.11"]
    assert matrix["n"] == [1, 2]
    assert matrix["include"] == [{"python-version": "3.10", "extra": "1.20"}]


def _ids(recipe_yaml):
    job = parse_recipe_string(recipe_yaml).jobs["j"]
    return [s.id for s in job.steps]


def test_generated_step_ids_avoid_every_explicit_id():
    recipe = (
        "on: push\njobs:\n  j:\n    steps:\n"
        "      - {uses: x/b4@v1}\n      - {uses: x/b4@v1}\n"
        "      - {id: b4_1, uses: x/b5@v1}\n"
    )
    assert _ids(recipe) == ["b4", "b4_2", "b4_1"]
    specs = {
        "x/b4@v1": mk_spec("x/b4@v1"),
        "x/b5@v1": mk_spec("x/b5@v1", inputs={"i": {}}),
    }
    wf = _compile(recipe, specs, config={"b4_1__i": "mine"})
    steps = wf["jobs"]["j"]["steps"]
    assert [s["id"] for s in steps] == ["b4", "b4_2", "b4_1"]
    assert "with" not in steps[1]  # the b5 step's scoped config did not leak


def test_an_explicit_id_wins_over_a_derived_one_that_came_first():
    recipe = "on: push\njobs:\n  j:\n    steps:\n      - {uses: x/b4@v1}\n      - {id: b4, run: x}\n"
    assert _ids(recipe) == ["b4_1", "b4"]


@pytest.mark.parametrize("second", ["b", "B"])
def test_two_explicit_steps_with_the_same_id_are_refused(second):
    recipe = f"on: push\njobs:\n  j:\n    steps:\n      - {{id: b, run: x}}\n      - {{id: {second}, run: y}}\n"
    with pytest.raises(RecipeParseError, match="two steps with the id"):
        parse_recipe_string(recipe)


def test_derived_ids_differing_only_in_case_are_made_distinct():
    recipe = "on: push\njobs:\n  j:\n    steps:\n      - {uses: x/Lint@v1}\n      - {uses: x/lint@v1}\n"
    ids = _ids(recipe)
    assert len({i.casefold() for i in ids}) == 2


def test_runs_on_may_be_a_list_or_mapping_with_config_refs():
    wf = _compile(
        "on: push\njobs:\n  j:\n    runs-on: [self-hosted, '${{ config.os }}']\n"
        "    steps: [{run: x}]\n",
        config={"os": "linux"},
    )
    assert wf["jobs"]["j"]["runs-on"] == ["self-hosted", "${{ needs.setup.outputs.os }}"]
