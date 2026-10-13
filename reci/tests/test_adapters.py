"""Config adapters: registry, auto-detection, read -> write -> read round trips."""

import json

import pytest

from reci.adapters import detect_adapter, get_adapter
from reci.adapters.base import ConfigAdapter
from reci.adapters.package_json import PackageJsonAdapter
from reci.adapters.pyproject import PyprojectTomlAdapter, _flatten
from reci.adapters.wads import WadsAdapter
from reci.adapters.yaml_adapter import YamlAdapter

PYPROJECT = """\
[project]
name = "demo"  # keep me

[tool.ci]
python_versions = ["3.10", "3.12"]  # comment survives

[tool.ci.testing]
coverage = true
threshold = 80

[tool.wads.ci]
installer = "uv"

[tool.wads.ci.testing]
pytest_args = ["-v"]
"""


@pytest.mark.parametrize(
    "name, cls",
    [
        ("pyproject", PyprojectTomlAdapter),
        ("wads", WadsAdapter),
        ("package-json", PackageJsonAdapter),
        ("yaml", YamlAdapter),
    ],
)
def test_registry_returns_each_adapter_and_satisfies_the_protocol(name, cls):
    adapter = get_adapter(name)
    assert type(adapter) is cls and isinstance(adapter, ConfigAdapter)


def test_registry_rejects_unknown_names():
    with pytest.raises(ValueError, match="Unknown config adapter: 'toml'"):
        get_adapter("toml")


def test_default_paths():
    assert [
        get_adapter(n).default_path()
        for n in ("pyproject", "wads", "package-json", "yaml")
    ] == [
        "pyproject.toml",
        "pyproject.toml",
        "package.json",
        ".ci.yml",
    ]


def test_detect_adapter_precedence(tmp_path):
    assert detect_adapter(str(tmp_path)) is None
    (tmp_path / ".ci.yml").write_text("a: 1\n")
    assert isinstance(detect_adapter(str(tmp_path)), YamlAdapter)
    (tmp_path / "package.json").write_text("{}")
    assert isinstance(detect_adapter(str(tmp_path)), PackageJsonAdapter)
    (tmp_path / "pyproject.toml").write_text("")
    assert isinstance(detect_adapter(str(tmp_path)), PyprojectTomlAdapter)


def test_flatten_joins_nested_keys_with_double_underscore():
    assert _flatten({"a": {"b": 1, "c": {"d": 2}}, "e": [1]}) == {
        "a__b": 1,
        "a__c__d": 2,
        "e": [1],
    }


def test_pyproject_reads_only_its_own_section(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text(PYPROJECT)
    assert PyprojectTomlAdapter().read(str(p)) == {
        "python_versions": ["3.10", "3.12"],
        "testing__coverage": True,
        "testing__threshold": 80,
    }
    assert WadsAdapter().read(str(p)) == {
        "installer": "uv",
        "testing__pytest_args": ["-v"],
    }


def test_pyproject_missing_section_reads_empty(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text('[project]\nname = "x"\n')
    assert PyprojectTomlAdapter().read(str(p)) == {}
    assert WadsAdapter().read(str(p)) == {}


def test_pyproject_write_preserves_the_rest_of_the_file_and_round_trips(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text(PYPROJECT)
    ad = PyprojectTomlAdapter()
    cfg = ad.read(str(p))
    cfg["new_key"] = "v"
    ad.write(str(p), cfg)
    text = p.read_text()
    assert 'name = "demo"  # keep me' in text  # formatting + comments kept
    assert "[tool.wads.ci]" in text and 'installer = "uv"' in text  # sibling tables
    assert ad.read(str(p)) == cfg  # parse -> emit -> parse is stable


def test_pyproject_write_creates_missing_sections(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text('[project]\nname = "x"\n')
    WadsAdapter().write(str(p), {"installer": "uv"})
    assert WadsAdapter().read(str(p)) == {"installer": "uv"}
    assert PyprojectTomlAdapter().read(str(p)) == {}  # did not leak into [tool.ci]


def test_package_json_round_trip_and_other_keys_preserved(tmp_path):
    p = tmp_path / "package.json"
    p.write_text(json.dumps({"name": "pkg", "ci": {"node": {"version": 20}}}))
    ad = PackageJsonAdapter()
    cfg = ad.read(str(p))
    assert cfg == {"node__version": 20}
    ad.write(str(p), {**cfg, "extra": [1, 2]})
    assert json.loads(p.read_text())["name"] == "pkg"
    assert p.read_text().endswith("}\n")
    assert ad.read(str(p)) == {"node__version": 20, "extra": [1, 2]}


def test_package_json_write_keeps_the_nested_structure(tmp_path):
    p = tmp_path / "package.json"
    p.write_text(json.dumps({"ci": {"node": {"version": 20}}}))
    ad = PackageJsonAdapter()
    ad.write(str(p), ad.read(str(p)))
    assert json.loads(p.read_text())["ci"] == {"node": {"version": 20}}


def test_pyproject_write_does_not_duplicate_nested_keys(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text(PYPROJECT)
    ad = PyprojectTomlAdapter()
    ad.write(str(p), ad.read(str(p)))
    assert p.read_text().count("coverage") == 1


def test_pyproject_write_keeps_comments_inside_its_own_section(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text(PYPROJECT)
    ad = PyprojectTomlAdapter()
    ad.write(str(p), {"python_versions": ["3.10", "3.12"]})
    assert "# comment survives" in p.read_text()


def test_package_json_without_ci_key_reads_empty(tmp_path):
    p = tmp_path / "package.json"
    p.write_text('{"name": "x"}')
    assert PackageJsonAdapter().read(str(p)) == {}


def test_yaml_round_trip(tmp_path):
    p = tmp_path / ".ci.yml"
    p.write_text("python_versions: ['3.10']\ntesting:\n  coverage: true\n")
    ad = YamlAdapter()
    cfg = ad.read(str(p))
    assert cfg == {"python_versions": ["3.10"], "testing__coverage": True}
    ad.write(str(p), cfg)
    assert ad.read(str(p)) == cfg


@pytest.mark.parametrize("text", ["", "- a\n- b\n"])
def test_yaml_non_mapping_reads_empty(tmp_path, text):
    p = tmp_path / ".ci.yml"
    p.write_text(text)
    assert YamlAdapter().read(str(p)) == {}


def test_package_json_write_keeps_non_ascii_characters_readable(tmp_path):
    p = tmp_path / "package.json"
    p.write_text("{}")
    PackageJsonAdapter().write(str(p), {"name": "café"})
    assert "café" in p.read_text()


def test_yaml_write_keeps_nested_structure_and_comments(tmp_path):
    p = tmp_path / ".ci.yml"
    p.write_text("# top comment\ntesting:\n  coverage: true  # keep\nname: x\n")
    ad = YamlAdapter()
    ad.write(str(p), {**ad.read(str(p)), "testing__coverage": False, "extra": 1})
    text = p.read_text()
    assert "# top comment" in text and "# keep" in text
    assert ad.read(str(p)) == {"testing__coverage": False, "name": "x", "extra": 1}
    assert "testing__coverage" not in text  # updated in place, not duplicated


def test_yaml_write_creates_a_missing_file(tmp_path):
    p = tmp_path / "new.yml"
    YamlAdapter().write(str(p), {"a": 1})
    assert YamlAdapter().read(str(p)) == {"a": 1}


@pytest.mark.parametrize("adapter_name", ["pyproject", "wads", "package-json", "yaml"])
def test_write_updates_nested_leaves_in_place_and_keeps_new_keys_flat(
    tmp_path, adapter_name
):
    ad = get_adapter(adapter_name)
    p = tmp_path / ad.default_path()
    p.write_text(
        {
            "pyproject": PYPROJECT,
            "wads": PYPROJECT,
            "package-json": json.dumps({"ci": {"testing": {"threshold": 80}}}),
            "yaml": "testing:\n  threshold: 80\n",
        }[adapter_name]
    )
    key, leaf = (
        ("testing__pytest_args", "pytest_args")
        if adapter_name == "wads"
        else ("testing__threshold", "threshold")
    )
    ad.write(str(p), {key: 90, "scoped__new": "v"})
    got = ad.read(str(p))
    assert got[key] == 90 and got["scoped__new"] == "v"
    assert p.read_text().count(leaf) == 1  # updated in place, no flat duplicate


def test_package_json_null_ci_and_yaml_top_level_list_are_replaced_by_a_mapping(
    tmp_path,
):
    p = tmp_path / "package.json"
    p.write_text('{"name": "x", "ci": null}')
    ad = PackageJsonAdapter()
    assert ad.read(str(p)) == {}
    ad.write(str(p), {"a": 1})
    assert json.loads(p.read_text()) == {"name": "x", "ci": {"a": 1}}

    y = tmp_path / ".ci.yml"
    y.write_text("- not\n- a mapping\n")
    YamlAdapter().write(str(y), {"a": 1})
    assert YamlAdapter().read(str(y)) == {"a": 1}


@pytest.mark.parametrize("adapter_name", ["pyproject", "package-json", "yaml"])
def test_a_new_key_under_an_existing_table_goes_inside_that_table(
    tmp_path, adapter_name
):
    ad = get_adapter(adapter_name)
    p = tmp_path / ad.default_path()
    p.write_text(
        {
            "pyproject": PYPROJECT,
            "package-json": json.dumps({"ci": {"testing": {"threshold": 80}}}),
            "yaml": "testing:\n  threshold: 80\n",
        }[adapter_name]
    )
    ad.write(str(p), {"testing__fresh": 1, "other__fresh": 2})
    assert ad.read(str(p))["testing__fresh"] == 1
    text = p.read_text()
    assert "testing__fresh" not in text  # nested under [testing], not flat
    assert "other__fresh" in text  # no such table: stays flat
