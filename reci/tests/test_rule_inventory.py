"""The documented rule inventory matches the registered rules (i2mint/reci#12).

The README's validation table, the rule modules' docstrings and the agent map in
``.claude/CLAUDE.md`` each name rule IDs; every one they name must be registered,
and the README table must name every registered rule.
"""

import re
from pathlib import Path

import pytest

from reci.validation import rules

ROOT = Path(__file__).resolve().parents[2]
RULE_ID = re.compile(r"\b(?:DAG|FLOW|CONF|PURE|ACT)\d{3}\b")


def _registered() -> set[str]:
    rules._ensure_rules_loaded()
    return set(rules._RULES)


def _readme_table_ids() -> set[str]:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    return {m.group(1) for m in re.finditer(r"^\| ((?:DAG|FLOW|CONF|PURE|ACT)\d{3}) \|", text, re.M)}


def test_the_readme_table_lists_exactly_the_registered_rules():
    assert _readme_table_ids() == _registered()


@pytest.mark.parametrize("module", ["dag", "flow", "config_rules", "purity", "action"])
def test_a_rule_module_docstring_names_only_its_registered_rules(module):
    path = Path(rules.__file__).parent / f"{module}.py"
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    named = set(RULE_ID.findall(first_line))
    for prefix, lo, hi in re.findall(r"\b([A-Z]+)(\d{3})[–-]\1(\d{3})\b", first_line):
        named |= {f"{prefix}{n:03d}" for n in range(int(lo), int(hi) + 1)}  # a range names all
    assert named and named <= _registered(), (module, named - _registered())


def test_the_agent_map_names_only_registered_rules():
    claude_md = ROOT / ".claude" / "CLAUDE.md"
    if not claude_md.exists():
        pytest.skip("no .claude/CLAUDE.md in this checkout")
    line = next(l for l in claude_md.read_text(encoding="utf-8").splitlines() if "**Validation rules**" in l)
    named = set(RULE_ID.findall(line))
    assert named == _registered()
