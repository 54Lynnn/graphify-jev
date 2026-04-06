"""Tests for graphify install --platform routing."""
from pathlib import Path
from unittest.mock import patch
import pytest


PLATFORMS = {
    "claude": (".claude/skills/graphify/SKILL.md",),
    "codex": (".agents/skills/graphify/SKILL.md",),
    "opencode": (".config/opencode/skills/graphify/SKILL.md",),
    "claw": (".claw/skills/graphify/SKILL.md",),
}


def _install(tmp_path, platform):
    from graphify.__main__ import install
    with patch("graphify.__main__.Path.home", return_value=tmp_path):
        install(platform=platform)


def test_install_default_claude(tmp_path):
    _install(tmp_path, "claude")
    assert (tmp_path / ".claude" / "skills" / "graphify" / "SKILL.md").exists()


def test_install_codex(tmp_path):
    _install(tmp_path, "codex")
    assert (tmp_path / ".agents" / "skills" / "graphify" / "SKILL.md").exists()


def test_install_opencode(tmp_path):
    _install(tmp_path, "opencode")
    assert (tmp_path / ".config" / "opencode" / "skills" / "graphify" / "SKILL.md").exists()


def test_install_claw(tmp_path):
    _install(tmp_path, "claw")
    assert (tmp_path / ".claw" / "skills" / "graphify" / "SKILL.md").exists()


def test_install_unknown_platform_exits(tmp_path):
    with pytest.raises(SystemExit):
        _install(tmp_path, "unknown")


def test_codex_skill_contains_spawn_agent():
    """Codex skill file must reference spawn_agent."""
    import graphify
    skill = (Path(graphify.__file__).parent / "skill-codex.md").read_text()
    assert "spawn_agent" in skill


def test_opencode_skill_contains_mention():
    """OpenCode skill file must reference @mention."""
    import graphify
    skill = (Path(graphify.__file__).parent / "skill-opencode.md").read_text()
    assert "@mention" in skill


def test_claw_skill_is_sequential():
    """OpenClaw skill file must describe sequential extraction."""
    import graphify
    skill = (Path(graphify.__file__).parent / "skill-claw.md").read_text()
    assert "sequential" in skill.lower()
    assert "spawn_agent" not in skill
    assert "@mention" not in skill


def test_all_skill_files_exist_in_package():
    """All four platform skill files must be present in the installed package."""
    import graphify
    pkg = Path(graphify.__file__).parent
    for name in ("skill.md", "skill-codex.md", "skill-opencode.md", "skill-claw.md"):
        assert (pkg / name).exists(), f"Missing: {name}"


def test_claude_install_registers_claude_md(tmp_path):
    """Claude platform install writes CLAUDE.md; others do not."""
    _install(tmp_path, "claude")
    assert (tmp_path / ".claude" / "CLAUDE.md").exists()


def test_codex_install_does_not_write_claude_md(tmp_path):
    _install(tmp_path, "codex")
    assert not (tmp_path / ".claude" / "CLAUDE.md").exists()
