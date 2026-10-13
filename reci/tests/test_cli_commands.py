"""CLI command bodies end to end (grammar is pinned in ``test_cli_surface``).

Action metadata is served from an in-memory table instead of GitHub.
"""

import json

import pytest

from reci import __main__ as cli
from reci.action_spec import ActionFetchError
from reci.tests._helpers import mk_spec

SPECS = {
    "x/a@v1": mk_spec(
        "x/a@v1", inputs={"w": {"required": True}}, outputs=["v"]
    ),
    "x/b@v1": mk_spec(
        "x/b@v1", inputs={"v": {"required": True}}, outputs=["w"]
    ),
    "x/build@v1": mk_spec(
        "x/build@v1", inputs={"python_version": {"required": True}}, outputs=["wheel"]
    ),
    "x/test@v1": mk_spec("x/test@v1", inputs={"wheel": {"required": True}}),
    "x/opt@v1": mk_spec(
        "x/opt@v1", inputs={"flavor": {"default": "vanilla"}, "tag": {}, "n": {"required": True}}
    ),
}
RECIPE = """\
name: demo
on: push
jobs:
  t:
    steps:
      - {id: build, uses: x/build@v1}
      - {id: test, uses: x/test@v1}
"""


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def fake(ref):
        if ref in SPECS:
            return SPECS[ref]
        raise ActionFetchError(f"no such action {ref}")

    monkeypatch.setattr(cli, "action_spec_from_ref", fake)


@pytest.fixture
def project(tmp_path):
    (tmp_path / "recipe.yml").write_text(RECIPE)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "p"\n\n[tool.ci]\npython_version = "3.12"\n'
    )
    return tmp_path


def test_compile_writes_the_workflow(project, capsys):
    out = project / "out" / "ci.yml"
    cli.compile(
        str(project / "recipe.yml"),
        config_path=str(project / "pyproject.toml"),
        output=str(out),
    )
    text = out.read_text()
    assert "python_version: '${{ needs.setup.outputs.python_version }}'" in text
    assert "wheel: '${{ steps.build.outputs.wheel }}'" in text
    assert f"Wrote {out}" in capsys.readouterr().out


def test_compile_aborts_on_validation_errors_and_writes_nothing(project, capsys):
    out = project / "ci.yml"
    with pytest.raises(SystemExit) as e:  # config lacks the required python_version
        cli.compile(
            str(project / "recipe.yml"),
            config_path=str(project / "missing.toml"),
            output=str(out),
        )
    assert e.value.code == 1 and not out.exists()
    err = capsys.readouterr().err
    assert "CONF001" in err and "Compilation aborted" in err


def test_unfetchable_action_warns_then_fails_validation(project, capsys):
    (project / "bad.yml").write_text(
        "on: push\njobs:\n  j:\n    steps:\n      - {uses: ghost/action@v1}\n"
    )
    with pytest.raises(SystemExit) as e:
        cli.validate(recipe=str(project / "bad.yml"))
    assert e.value.code == 1
    cap = capsys.readouterr()
    assert "no such action ghost/action@v1" in cap.err and "ACT002" in cap.out


def test_validate_formats_and_exit_codes(project, capsys):
    cfg = str(project / "pyproject.toml")
    recipe = str(project / "recipe.yml")
    cli.validate(recipe=recipe, config_path=cfg, format="json")  # no errors: returns
    items = json.loads(capsys.readouterr().out)
    assert not any(i["severity"] == "error" for i in items)

    cli.validate(recipe=recipe, config_path=cfg, format="github")
    assert capsys.readouterr().out.strip() == ""  # a clean recipe annotates nothing

    (project / "w.yml").write_text(
        "on: push\njobs:\n  j:\n    steps:\n      - {id: r, run: make}\n"
    )
    cli.validate(recipe=str(project / "w.yml"), format="github")
    assert capsys.readouterr().out.startswith("::warning file=j.r::[PURE001]")


def test_validate_max_warnings_gate(project, capsys):
    (project / "w.yml").write_text(
        "on: push\njobs:\n  j:\n    steps:\n      - {id: r, run: make}\n"
    )
    cli.validate(recipe=str(project / "w.yml"), max_warnings=1)  # 1 warning, allowed 1
    with pytest.raises(SystemExit) as e:
        cli.validate(recipe=str(project / "w.yml"), max_warnings=0)
    assert e.value.code == 1
    assert "Too many warnings: 1 (max 0)" in capsys.readouterr().err


def test_scaffold_fills_missing_keys_without_clobbering_existing(project, capsys):
    cfg = project / "pyproject.toml"
    cli.scaffold(
        str(project / "recipe.yml"),
        config_path=str(cfg),
        output=str(project / "ci.yml"),
    )
    text = cfg.read_text()
    assert 'python_version = "3.12"' in text  # existing value kept
    assert "<REQUIRED: python_version>" not in text  # present: not overwritten
    assert (project / "ci.yml").exists()
    assert "Updated config" in capsys.readouterr().out


def test_load_config_missing_file_is_empty(tmp_path):
    assert cli._load_config(config_path=str(tmp_path / "nope.toml")) == {}


def test_inspect_prints_the_contract(capsys):
    cli.inspect("x/build@v1")
    out = capsys.readouterr().out
    assert "Action: x/build@v1" in out
    assert "python_version (required)" in out and "Outputs:\n  wheel" in out
    cli.inspect("x/test@v1")
    assert "Outputs: none" in capsys.readouterr().out


def test_scaffold_does_not_ask_for_inputs_an_upstream_step_supplies(project):
    cfg = project / "pyproject.toml"
    cli.scaffold(
        str(project / "recipe.yml"),
        config_path=str(cfg),
        output=str(project / "ci.yml"),
    )
    assert "<REQUIRED: wheel>" not in cfg.read_text()


def test_scaffold_writes_a_placeholder_for_a_truly_missing_required_input(project):
    cfg = project / "empty.toml"
    cfg.write_text("")
    cli.scaffold(
        str(project / "recipe.yml"),
        config_path=str(cfg),
        output=str(project / "ci.yml"),
    )
    assert "<REQUIRED: python_version>" in cfg.read_text()


def test_scaffold_leaves_optional_inputs_to_the_action_default(project):
    (project / "opt.yml").write_text(
        "on: push\njobs:\n  t:\n    steps: [{id: o, uses: x/opt@v1}]\n"
    )
    cfg = project / "empty.toml"
    cfg.write_text("")
    out = project / "opt-ci.yml"
    cli.scaffold(str(project / "opt.yml"), config_path=str(cfg), output=str(out))
    text = cfg.read_text()
    assert "<REQUIRED: n>" in text
    assert "flavor" not in text and "tag" not in text
    assert "flavor" not in out.read_text()  # the action default applies


def test_scaffold_keeps_a_cross_job_consumer_on_the_upstream_output(
    project, monkeypatch
):
    (project / "x.yml").write_text(
        "on: push\njobs:\n  build:\n    steps: [{id: p, uses: x/p@v1}]\n"
        "  test:\n    steps: [{id: c, uses: x/test@v1}]\n"
    )
    spec = mk_spec("x/p@v1", inputs={"wheel": {}}, outputs=["wheel"])
    monkeypatch.setitem(SPECS, "x/p@v1", spec)
    cfg = project / "empty.toml"
    cfg.write_text("")
    out = project / "x-ci.yml"
    cli.scaffold(str(project / "x.yml"), config_path=str(cfg), output=str(out))
    assert "wheel" not in cfg.read_text()
    assert "needs.build.outputs.wheel" in out.read_text()


def test_compile_reports_a_data_flow_needs_cycle_as_a_finding_not_a_traceback(
    project, capsys
):
    (project / "loop.yml").write_text(
        "on: push\njobs:\n  a:\n    steps: [{id: s, uses: x/a@v1}]\n"
        "  b:\n    steps: [{id: t, uses: x/b@v1}]\n"
    )
    out = project / "ci.yml"
    with pytest.raises(SystemExit) as e:
        cli.compile(
            str(project / "loop.yml"),
            config_path=str(project / "pyproject.toml"),
            output=str(out),
        )
    assert e.value.code == 1
    err = capsys.readouterr().err
    assert "DAG005" in err and "reads 'v' from 'a.s'" in err
    assert "Compilation aborted" in err and not out.exists()


def test_a_compilation_error_exits_cleanly_without_a_traceback(
    project, capsys, monkeypatch
):
    def boom(*args, **kwargs):
        raise cli.CompilationError("boom")

    monkeypatch.setattr(cli, "compile_recipe", boom)
    with pytest.raises(SystemExit) as e:
        cli.compile(
            str(project / "recipe.yml"),
            config_path=str(project / "pyproject.toml"),
            output=str(project / "ci.yml"),
        )
    assert e.value.code == 1
    assert capsys.readouterr().err.endswith("error: boom\n")


def test_compile_reports_a_job_named_setup_when_config_is_supplied(project, capsys):
    (project / "clash.yml").write_text(
        "on: push\njobs:\n  setup:\n    steps: [{run: echo}]\n"
    )
    with pytest.raises(SystemExit):
        cli.compile(
            str(project / "clash.yml"),
            config_path=str(project / "pyproject.toml"),
            output=str(project / "ci.yml"),
        )
    assert "DAG007" in capsys.readouterr().err


def test_scaffold_adds_the_config_keys_the_recipe_references(project):
    (project / "refs.yml").write_text(
        "on: push\njobs:\n  j:\n    steps: [{run: 'echo ${{ config.greeting }}'}]\n"
    )
    cfg = project / "empty.toml"
    cfg.write_text("")
    cli.scaffold(
        str(project / "refs.yml"), config_path=str(cfg), output=str(project / "ci.yml")
    )
    assert "<REQUIRED: greeting>" in cfg.read_text()
    assert (project / "ci.yml").exists()


@pytest.mark.parametrize(
    "adapter, name", [("pyproject", "pyproject.toml"), ("package-json", "package.json")]
)
def test_scaffold_creates_the_config_file_when_there_is_none(project, adapter, name):
    cfg = project / "fresh" / name
    cfg.parent.mkdir()
    cli.scaffold(
        str(project / "recipe.yml"),
        config_adapter=adapter,
        config_path=str(cfg),
        output=str(project / "ci.yml"),
    )
    assert "<REQUIRED: python_version>" in cfg.read_text()
    assert (project / "ci.yml").exists()


def test_scaffold_of_a_refused_recipe_writes_neither_config_nor_workflow(
    project, capsys
):
    (project / "bad.yml").write_text(
        "on: push\njobs:\n  t:\n    steps:\n"
        "      - {id: build, uses: x/build@v1, with: {python_version: '${{ config.nope.x }}'}}\n"
    )
    cfg = project / "cfg.toml"
    out = project / "bad-ci.yml"
    with pytest.raises(SystemExit) as e:
        cli.scaffold(str(project / "bad.yml"), config_path=str(cfg), output=str(out))
    assert e.value.code == 1
    assert not cfg.exists() and not out.exists()
    assert "CONF004" in capsys.readouterr().err


def test_scaffold_accepts_a_config_ref_that_differs_from_a_key_only_in_case(project):
    (project / "ref.yml").write_text(
        "on: push\njobs:\n  t:\n    steps: [{run: x, name: '${{ config.OS }}'}]\n"
    )
    cfg = project / "pyproject.toml"
    cfg.write_text('[tool.ci]\nos = "ubuntu-latest"\n')
    cli.scaffold(
        str(project / "ref.yml"), config_path=str(cfg), output=str(project / "ci.yml")
    )
    assert "<REQUIRED" not in cfg.read_text()
