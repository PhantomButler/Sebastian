from __future__ import annotations

from pathlib import Path


def test_skill_loader_reads_skill_md(tmp_path: Path) -> None:
    """Loader finds SKILL.md files and creates tool specs."""
    skill_dir = tmp_path / "my_skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: my_skill\ndescription: Does my thing\n---\n\nSteps: do stuff.\n"
    )

    from sebastian.capabilities.skills._loader import load_skills

    skills = load_skills(extra_dirs=[tmp_path])

    assert len(skills) == 1
    assert skills[0]["name"] == "skill__my_skill"
    assert "Does my thing" in skills[0]["description"]


def test_skill_loader_skips_dirs_without_skill_md(tmp_path: Path) -> None:
    no_skill_dir = tmp_path / "notaskill"
    no_skill_dir.mkdir()
    (no_skill_dir / "README.md").write_text("# not a skill")

    from sebastian.capabilities.skills._loader import load_skills

    skills = load_skills(extra_dirs=[tmp_path])
    assert len(skills) == 0


def test_skill_loader_user_dir_overrides_builtin(tmp_path: Path) -> None:
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    user_dir = tmp_path / "user"
    user_dir.mkdir()

    for base in [builtin_dir, user_dir]:
        sd = base / "greet"
        sd.mkdir()
        src = "builtin" if base == builtin_dir else "user"
        (sd / "SKILL.md").write_text(
            f"---\nname: greet\ndescription: Greet from {src}\n---\nGreet.\n"
        )

    from sebastian.capabilities.skills._loader import load_skills

    skills = load_skills(builtin_dir=builtin_dir, extra_dirs=[user_dir])
    greet = next(s for s in skills if s["name"] == "skill__greet")
    assert "user" in greet["description"]
