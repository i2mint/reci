"""The agent skills ship as package data and follow the Agent Skills layout.

Real files live in ``reci/data/skills/<name>/``; ``.claude/skills/<name>`` are relative
symlinks into them (the bridge Claude Code reads). See the skill-package-setup policy.
"""

import re
from importlib import resources
from pathlib import Path

import pytest

SKILLS = resources.files("reci") / "data" / "skills"
REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_NAMES = ("ci-advisor", "ci-migrate", "ci-setup", "reci-dev")


def _frontmatter(skill_md: str) -> str:
    match = re.match(r"---\n(.*?)\n---\n", skill_md, re.DOTALL)
    assert match, "SKILL.md must start with a YAML frontmatter block"
    return match.group(1)


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_skill_is_packaged_and_spec_clean(name):
    text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
    front = _frontmatter(text)
    assert re.search(rf"^name: {name}$", front, re.MULTILINE)
    description = re.search(r"^description: >\n((?:  .*\n?)+)", front, re.MULTILINE)
    assert description, "description is required"
    assert len(" ".join(description.group(1).split())) <= 1024
    assert text.count("\n") < 500


def test_no_unexpected_skills():
    found = sorted(p.name for p in SKILLS.iterdir() if (p / "SKILL.md").is_file())
    assert found == sorted(SKILL_NAMES)


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_claude_bridge_is_a_relative_symlink_into_the_package(name):
    link = REPO_ROOT / ".claude" / "skills" / name
    if not link.parent.exists():  # an installed copy has no checkout around it
        pytest.skip("not running from a source checkout")
    assert link.is_symlink()
    target = link.readlink()
    assert not target.is_absolute()
    assert link.resolve() == Path(str(SKILLS / name)).resolve()
