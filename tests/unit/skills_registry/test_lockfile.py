from __future__ import annotations

import contextlib
import json
import multiprocessing
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sebastian.skills_registry import lockfile as lockfile_module
from sebastian.skills_registry.lockfile import (
    LockfileEntry,
    LockfileError,
    SkillPackageLock,
    with_package_lock,
)


def test_lockfile_round_trip(tmp_path: Path) -> None:
    entry = LockfileEntry(
        slug="flight",
        registered_name="skill__flight",
        registry="https://clawhub.ai",
        version="1.2.3",
        tag="stable",
        sha256="abc123",
        fingerprint="def456",
        installed_at=datetime(2026, 5, 8, tzinfo=UTC).isoformat(),
    )

    SkillPackageLock(tmp_path).update_entry(entry)

    assert SkillPackageLock(tmp_path).load() == {"flight": entry}

    payload = json.loads((tmp_path / ".sebastian-skills.lock.json").read_text())
    assert payload["version"] == 1
    assert payload["skills"]["flight"] == {
        "fingerprint": "def456",
        "installed_at": entry.installed_at,
        "registered_name": "skill__flight",
        "registry": "https://clawhub.ai",
        "sha256": "abc123",
        "slug": "flight",
        "tag": "stable",
        "version": "1.2.3",
    }


def test_update_entry_uses_package_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[Path] = []

    @contextlib.contextmanager
    def fake_package_lock(root: Path) -> Iterator[None]:
        calls.append(root)
        yield

    monkeypatch.setattr(lockfile_module, "with_package_lock", fake_package_lock)
    entry = LockfileEntry(
        slug="flight",
        registered_name="skill__flight",
        registry="https://clawhub.ai",
        version=None,
        tag=None,
        sha256=None,
        fingerprint="abc123",
        installed_at=datetime(2026, 5, 8, tzinfo=UTC).isoformat(),
    )

    SkillPackageLock(tmp_path).update_entry(entry)

    assert calls == [tmp_path]


def test_package_lock_covers_entire_transaction(tmp_path: Path) -> None:
    marker = tmp_path / "marker"

    with with_package_lock(tmp_path):
        marker.write_text("locked", encoding="utf-8")

    assert marker.read_text(encoding="utf-8") == "locked"


def test_package_lock_blocks_contending_process(tmp_path: Path) -> None:
    first_ready = multiprocessing.Event()
    release_first = multiprocessing.Event()
    second_acquired = multiprocessing.Event()
    first = multiprocessing.Process(
        target=_hold_package_lock,
        args=(tmp_path, first_ready, release_first),
    )
    second = multiprocessing.Process(
        target=_acquire_package_lock,
        args=(tmp_path, second_acquired),
    )

    first.start()
    try:
        assert first_ready.wait(timeout=5)
        second.start()
        time.sleep(0.2)
        assert not second_acquired.is_set()
        release_first.set()
        assert second_acquired.wait(timeout=5)
    finally:
        release_first.set()
        first.join(timeout=5)
        second.join(timeout=5)
        if first.is_alive():
            first.terminate()
        if second.is_alive():
            second.terminate()

    assert first.exitcode == 0
    assert second.exitcode == 0


def test_save_fsyncs_parent_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fsynced_dirs: list[Path] = []

    def fake_fsync_directory(path: Path) -> None:
        fsynced_dirs.append(path)

    monkeypatch.setattr(lockfile_module, "_fsync_directory", fake_fsync_directory)
    entry = LockfileEntry(
        slug="flight",
        registered_name="skill__flight",
        registry="https://clawhub.ai",
        version=None,
        tag=None,
        sha256=None,
        fingerprint="abc123",
        installed_at=datetime(2026, 5, 8, tzinfo=UTC).isoformat(),
    )

    SkillPackageLock(tmp_path).save({"flight": entry})

    assert fsynced_dirs == [tmp_path]


def test_load_rejects_malformed_json(tmp_path: Path) -> None:
    (tmp_path / ".sebastian-skills.lock.json").write_text("{", encoding="utf-8")

    with pytest.raises(LockfileError):
        SkillPackageLock(tmp_path).load()


def test_load_rejects_malformed_entry(tmp_path: Path) -> None:
    (tmp_path / ".sebastian-skills.lock.json").write_text(
        json.dumps({"version": 1, "skills": {"flight": {"slug": "flight"}}}),
        encoding="utf-8",
    )

    with pytest.raises(LockfileError):
        SkillPackageLock(tmp_path).load()


def test_load_rejects_non_object_entry(tmp_path: Path) -> None:
    (tmp_path / ".sebastian-skills.lock.json").write_text(
        json.dumps({"version": 1, "skills": {"flight": "broken"}}),
        encoding="utf-8",
    )

    with pytest.raises(LockfileError):
        SkillPackageLock(tmp_path).load()


def test_load_rejects_non_string_slug(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / ".sebastian-skills.lock.json").write_text("{}", encoding="utf-8")

    def fake_json_load(file: object) -> dict[str, object]:
        return {
            "version": 1,
            "skills": {
                123: {
                    "slug": "flight",
                    "registered_name": "skill__flight",
                    "registry": "https://clawhub.ai",
                    "version": None,
                    "tag": None,
                    "sha256": None,
                    "fingerprint": "abc123",
                    "installed_at": datetime(2026, 5, 8, tzinfo=UTC).isoformat(),
                }
            },
        }

    monkeypatch.setattr(lockfile_module.json, "load", fake_json_load)

    with pytest.raises(LockfileError):
        SkillPackageLock(tmp_path).load()


def _hold_package_lock(
    root: Path,
    ready: multiprocessing.Event,
    release: multiprocessing.Event,
) -> None:
    with with_package_lock(root):
        ready.set()
        release.wait(timeout=5)


def _acquire_package_lock(root: Path, acquired: multiprocessing.Event) -> None:
    with with_package_lock(root):
        acquired.set()
