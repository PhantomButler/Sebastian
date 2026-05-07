from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import sebastian.capabilities.skills.hot_reload as hot_reload
from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.capabilities.skills._loader import load_skills
from sebastian.capabilities.skills.hot_reload import SkillHotReloader


def write_skill(base: Path, dirname: str, body: str) -> None:
    skill_dir = base / dirname
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")


@pytest.mark.asyncio
async def test_seeded_reloader_unchanged_returns_current_version(tmp_path: Path) -> None:
    write_skill(tmp_path, "travel", "---\nname: travel\ndescription: Travel\n---\nUse APIs.")
    reg = CapabilityRegistry()
    specs = load_skills(builtin_dir=tmp_path, extra_dirs=[])
    reg.replace_skill_specs(specs)
    reloader = SkillHotReloader.seeded(registry=reg, builtin_dir=tmp_path, extra_dirs=[])

    result = await reloader.maybe_reload()

    assert result.changed is False
    assert result.version == 0
    assert {s["name"] for s in reg.get_skill_specs()} == {"skill__travel"}


@pytest.mark.asyncio
async def test_edit_skill_md_reloads_and_increments_version(tmp_path: Path) -> None:
    write_skill(tmp_path, "travel", "---\nname: travel\ndescription: Old\n---\nOld.")
    reg = CapabilityRegistry()
    reg.replace_skill_specs(load_skills(builtin_dir=tmp_path, extra_dirs=[]))
    reloader = SkillHotReloader.seeded(registry=reg, builtin_dir=tmp_path, extra_dirs=[])

    write_skill(
        tmp_path,
        "travel",
        "---\nname: travel\ndescription: New and longer\n---\nNew body with more bytes.",
    )
    result = await reloader.maybe_reload()

    assert result.changed is True
    assert result.version == 1
    assert "New and longer" in reg.get_skill_specs()[0]["description"]


@pytest.mark.asyncio
async def test_delete_skill_md_reloads_and_removes_skill(tmp_path: Path) -> None:
    write_skill(tmp_path, "travel", "---\nname: travel\ndescription: Travel\n---\nUse APIs.")
    reg = CapabilityRegistry()
    reg.replace_skill_specs(load_skills(builtin_dir=tmp_path, extra_dirs=[]))
    reloader = SkillHotReloader.seeded(registry=reg, builtin_dir=tmp_path, extra_dirs=[])

    (tmp_path / "travel" / "SKILL.md").unlink()
    result = await reloader.maybe_reload()

    assert result.changed is True
    assert result.version == 1
    assert reg.get_skill_specs() == []


@pytest.mark.asyncio
async def test_adding_script_without_skill_md_edit_does_not_reload(tmp_path: Path) -> None:
    write_skill(tmp_path, "travel", "---\nname: travel\ndescription: Travel\n---\nUse APIs.")
    reg = CapabilityRegistry()
    reg.replace_skill_specs(load_skills(builtin_dir=tmp_path, extra_dirs=[]))
    reloader = SkillHotReloader.seeded(registry=reg, builtin_dir=tmp_path, extra_dirs=[])

    scripts_dir = tmp_path / "travel" / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "search_flights.py").write_text("print('fresh at execution time')\n")
    result = await reloader.maybe_reload()

    assert result.changed is False
    assert result.version == 0
    assert reloader.version == 0


@pytest.mark.asyncio
async def test_ignored_skill_dirs_do_not_trigger_reload(tmp_path: Path) -> None:
    write_skill(tmp_path, "travel", "---\nname: travel\ndescription: Travel\n---\nUse APIs.")
    reg = CapabilityRegistry()
    reg.replace_skill_specs(load_skills(builtin_dir=tmp_path, extra_dirs=[]))
    reloader = SkillHotReloader.seeded(registry=reg, builtin_dir=tmp_path, extra_dirs=[])

    write_skill(tmp_path, "_ignored", "---\nname: ignored\ndescription: Ignored\n---\nIgnore.")
    first = await reloader.maybe_reload()
    write_skill(tmp_path, "_ignored", "---\nname: ignored\ndescription: Edited\n---\nIgnore more.")
    second = await reloader.maybe_reload()

    assert first.changed is False
    assert second.changed is False
    assert reloader.version == 0
    assert {s["name"] for s in reg.get_skill_specs()} == {"skill__travel"}


@pytest.mark.asyncio
async def test_concurrent_reload_after_one_edit_increments_version_once(tmp_path: Path) -> None:
    write_skill(tmp_path, "travel", "---\nname: travel\ndescription: Old\n---\nOld.")
    reg = CapabilityRegistry()
    reg.replace_skill_specs(load_skills(builtin_dir=tmp_path, extra_dirs=[]))
    reloader = SkillHotReloader.seeded(registry=reg, builtin_dir=tmp_path, extra_dirs=[])

    write_skill(tmp_path, "travel", "---\nname: travel\ndescription: New\n---\nNew body.")
    results = await asyncio.gather(*(reloader.maybe_reload() for _ in range(5)))

    assert sum(result.changed for result in results) == 1
    assert reloader.version == 1
    assert "New" in reg.get_skill_specs()[0]["description"]


@pytest.mark.asyncio
async def test_startup_seed_catches_edit_before_first_reload_check(tmp_path: Path) -> None:
    write_skill(tmp_path, "travel", "---\nname: travel\ndescription: Seeded\n---\nSeeded.")
    reg = CapabilityRegistry()
    reg.replace_skill_specs(load_skills(builtin_dir=tmp_path, extra_dirs=[]))
    reloader = SkillHotReloader.seeded(registry=reg, builtin_dir=tmp_path, extra_dirs=[])

    write_skill(
        tmp_path,
        "travel",
        "---\nname: travel\ndescription: Edited and longer\n---\nEdited body grew.",
    )
    result = await reloader.maybe_reload()

    assert result.changed is True
    assert result.version == 1
    assert "Edited and longer" in reg.get_skill_specs()[0]["description"]


@pytest.mark.asyncio
async def test_reload_failure_keeps_old_state_and_next_call_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_skill(tmp_path, "travel", "---\nname: travel\ndescription: Old\n---\nOld.")
    reg = CapabilityRegistry()
    reg.replace_skill_specs(load_skills(builtin_dir=tmp_path, extra_dirs=[]))
    reloader = SkillHotReloader.seeded(registry=reg, builtin_dir=tmp_path, extra_dirs=[])

    calls = 0

    def fail_once(
        builtin_dir: Path | None = None,
        extra_dirs: list[Path] | None = None,
    ) -> list[dict[str, object]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("loader unavailable")
        return load_skills(builtin_dir=builtin_dir, extra_dirs=extra_dirs)

    write_skill(
        tmp_path,
        "travel",
        "---\nname: travel\ndescription: New and longer\n---\nNew body grew.",
    )
    monkeypatch.setattr(hot_reload, "load_skills", fail_once)

    failed = await reloader.maybe_reload()

    assert failed.changed is False
    assert failed.version == 0
    assert failed.error == "Skill hot reload failed"
    assert "Old" in reg.get_skill_specs()[0]["description"]

    retried = await reloader.maybe_reload()

    assert retried.changed is True
    assert retried.version == 1
    assert calls == 2
    assert "New and longer" in reg.get_skill_specs()[0]["description"]


@pytest.mark.asyncio
async def test_fingerprint_failure_keeps_old_state_and_next_call_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_skill(tmp_path, "travel", "---\nname: travel\ndescription: Old\n---\nOld.")
    reg = CapabilityRegistry()
    reg.replace_skill_specs(load_skills(builtin_dir=tmp_path, extra_dirs=[]))
    reloader = SkillHotReloader.seeded(registry=reg, builtin_dir=tmp_path, extra_dirs=[])

    calls = 0
    original_compute = hot_reload.compute_skill_fingerprint

    def fail_once(
        builtin_dir: Path,
        extra_dirs: list[Path] | None = None,
    ) -> hot_reload.SkillFingerprint:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("transient scan failure")
        return original_compute(builtin_dir, extra_dirs)

    write_skill(
        tmp_path,
        "travel",
        "---\nname: travel\ndescription: New and longer\n---\nNew body grew.",
    )
    monkeypatch.setattr(hot_reload, "compute_skill_fingerprint", fail_once)

    failed = await reloader.maybe_reload()

    assert failed.changed is False
    assert failed.version == 0
    assert failed.error == "Skill hot reload failed"
    assert "Old" in reg.get_skill_specs()[0]["description"]

    retried = await reloader.maybe_reload()

    assert retried.changed is True
    assert retried.version == 1
    assert calls == 2
    assert "New and longer" in reg.get_skill_specs()[0]["description"]
