from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import sebastian.capabilities.skills.hot_reload as hot_reload
from sebastian.capabilities.skills.hot_reload import SkillHotReloader


def write_skill(base: Path, dirname: str, body: str) -> None:
    skill_dir = base / dirname
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")


def _fingerprint_skill_dirs(fingerprint: hot_reload.SkillFingerprint) -> set[str]:
    dirs: set[str] = set()
    for entry in fingerprint:
        _, relative = entry.relative_path.split("::", maxsplit=1)
        dirs.add(Path(relative).parts[0])
    return dirs


@pytest.mark.asyncio
async def test_seeded_reloader_unchanged_returns_current_version(tmp_path: Path) -> None:
    write_skill(tmp_path, "travel", "---\nname: travel\ndescription: Travel\n---\nUse APIs.")
    reloader = SkillHotReloader.seeded(builtin_dir=tmp_path, extra_dirs=[])

    result = await reloader.maybe_reload()

    assert result.changed is False
    assert result.version == 0
    assert _fingerprint_skill_dirs(result.fingerprint) == {"travel"}


@pytest.mark.asyncio
async def test_add_skill_to_empty_extra_dir_updates_fingerprint(tmp_path: Path) -> None:
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    extra_dir = tmp_path / "extra"
    extra_dir.mkdir()
    reloader = SkillHotReloader.seeded(
        builtin_dir=builtin_dir,
        extra_dirs=[extra_dir],
    )

    write_skill(
        extra_dir,
        "flight",
        "---\nname: flight\ndescription: Flight search\n---\nFind flights.",
    )
    result = await reloader.maybe_reload()

    assert result.changed is True
    assert result.version == 1
    assert _fingerprint_skill_dirs(result.fingerprint) == {"flight"}


@pytest.mark.asyncio
async def test_edit_skill_md_increments_version(tmp_path: Path) -> None:
    write_skill(tmp_path, "travel", "---\nname: travel\ndescription: Old\n---\nOld.")
    reloader = SkillHotReloader.seeded(builtin_dir=tmp_path, extra_dirs=[])

    write_skill(
        tmp_path,
        "travel",
        "---\nname: travel\ndescription: New and longer\n---\nNew body with more bytes.",
    )
    result = await reloader.maybe_reload()

    assert result.changed is True
    assert result.version == 1
    assert _fingerprint_skill_dirs(result.fingerprint) == {"travel"}


@pytest.mark.asyncio
async def test_delete_skill_md_updates_fingerprint(tmp_path: Path) -> None:
    write_skill(tmp_path, "travel", "---\nname: travel\ndescription: Travel\n---\nUse APIs.")
    reloader = SkillHotReloader.seeded(builtin_dir=tmp_path, extra_dirs=[])

    (tmp_path / "travel" / "SKILL.md").unlink()
    result = await reloader.maybe_reload()

    assert result.changed is True
    assert result.version == 1
    assert result.fingerprint == ()


@pytest.mark.asyncio
async def test_adding_script_without_skill_md_edit_does_not_reload(tmp_path: Path) -> None:
    write_skill(tmp_path, "travel", "---\nname: travel\ndescription: Travel\n---\nUse APIs.")
    reloader = SkillHotReloader.seeded(builtin_dir=tmp_path, extra_dirs=[])

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
    reloader = SkillHotReloader.seeded(builtin_dir=tmp_path, extra_dirs=[])

    write_skill(tmp_path, "_ignored", "---\nname: ignored\ndescription: Ignored\n---\nIgnore.")
    first = await reloader.maybe_reload()
    write_skill(tmp_path, "_ignored", "---\nname: ignored\ndescription: Edited\n---\nIgnore more.")
    second = await reloader.maybe_reload()

    assert first.changed is False
    assert second.changed is False
    assert reloader.version == 0
    assert _fingerprint_skill_dirs(second.fingerprint) == {"travel"}


@pytest.mark.asyncio
async def test_concurrent_reload_after_one_edit_increments_version_once(tmp_path: Path) -> None:
    write_skill(tmp_path, "travel", "---\nname: travel\ndescription: Old\n---\nOld.")
    reloader = SkillHotReloader.seeded(builtin_dir=tmp_path, extra_dirs=[])

    write_skill(tmp_path, "travel", "---\nname: travel\ndescription: New\n---\nNew body.")
    results = await asyncio.gather(*(reloader.maybe_reload() for _ in range(5)))

    assert sum(result.changed for result in results) == 1
    assert reloader.version == 1
    assert _fingerprint_skill_dirs(results[0].fingerprint) == {"travel"}


@pytest.mark.asyncio
async def test_startup_seed_catches_edit_before_first_reload_check(tmp_path: Path) -> None:
    write_skill(tmp_path, "travel", "---\nname: travel\ndescription: Seeded\n---\nSeeded.")
    reloader = SkillHotReloader.seeded(builtin_dir=tmp_path, extra_dirs=[])

    write_skill(
        tmp_path,
        "travel",
        "---\nname: travel\ndescription: Edited and longer\n---\nEdited body grew.",
    )
    result = await reloader.maybe_reload()

    assert result.changed is True
    assert result.version == 1
    assert _fingerprint_skill_dirs(result.fingerprint) == {"travel"}


@pytest.mark.asyncio
async def test_fingerprint_failure_keeps_old_state_and_next_call_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_skill(tmp_path, "travel", "---\nname: travel\ndescription: Old\n---\nOld.")
    reloader = SkillHotReloader.seeded(builtin_dir=tmp_path, extra_dirs=[])

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
    assert _fingerprint_skill_dirs(failed.fingerprint) == {"travel"}

    retried = await reloader.maybe_reload()

    assert retried.changed is True
    assert retried.version == 1
    assert calls == 2
    assert _fingerprint_skill_dirs(retried.fingerprint) == {"travel"}
