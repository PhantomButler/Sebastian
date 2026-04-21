"""Unit tests for sebastian.cli.updater.

Network-dependent helpers (fetch_latest_tag / _download) are only exercised
indirectly via run_update with monkeypatched stubs — we don't hit github.com.
"""

from __future__ import annotations

import hashlib
import io
import os
import tarfile
from pathlib import Path

import pytest

from sebastian.cli import updater

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _build_release_tarball(dst: Path, version: str = "9.9.9") -> Path:
    """Build a github-style release tarball with the managed entries."""
    inner = f"sebastian-backend-v{version}"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:

        def add_bytes(name: str, data: bytes) -> None:
            info = tarfile.TarInfo(f"{inner}/{name}")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

        # sebastian/ as a dir with one file
        info = tarfile.TarInfo(f"{inner}/sebastian")
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        tf.addfile(info)
        add_bytes("sebastian/__init__.py", b"# new\n")

        # scripts/ as a dir with one file
        info = tarfile.TarInfo(f"{inner}/scripts")
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        tf.addfile(info)
        add_bytes("scripts/install.sh", b"#!/bin/sh\necho new\n")

        add_bytes("pyproject.toml", f'version = "{version}"\n'.encode())
        add_bytes("README.md", b"new readme\n")
        add_bytes("LICENSE", b"MIT\n")
        add_bytes("CHANGELOG.md", b"## new\n")

    out = dst / f"sebastian-backend-v{version}.tar.gz"
    out.write_bytes(buf.getvalue())
    return out


def _make_install_dir(root: Path) -> Path:
    """Create a fake install dir with the managed entries + an unmanaged file."""
    inst = root / "app"
    inst.mkdir()
    (inst / "pyproject.toml").write_text('version = "0.0.1"\n')
    (inst / "README.md").write_text("old readme\n")
    (inst / "LICENSE").write_text("old\n")
    (inst / "CHANGELOG.md").write_text("## old\n")

    pkg = inst / "sebastian"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("# old\n")

    scripts = inst / "scripts"
    scripts.mkdir()
    (scripts / "install.sh").write_text("#!/bin/sh\necho old\n")

    # Unmanaged things that must NOT be touched.
    (inst / ".env").write_text("SECRET=keep\n")
    venv = inst / ".venv"
    venv.mkdir()
    (venv / "marker").write_text("dont touch\n")
    return inst


def _write_project_version(root: Path, version: str) -> None:
    (root / "pyproject.toml").write_text(f'[project]\nname = "sebastian"\nversion = "{version}"\n')


@pytest.fixture()
def _patch_backup_parent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect backup directory to tmp_path/backups for all tests."""
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    monkeypatch.setattr(updater, "_backup_parent", lambda: backup_root)
    return backup_root


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def test_resolve_install_dir_prefers_bootstrap_install_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    inst = tmp_path / ".sebastian" / "app"
    inst.mkdir(parents=True)
    (inst / "sebastian").mkdir()
    _write_project_version(inst, "1.2.3")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SEBASTIAN_INSTALL_DIR", raising=False)

    assert updater.resolve_install_dir() == inst


def test_current_version_reads_install_dir_pyproject(tmp_path: Path) -> None:
    inst = tmp_path / "app"
    inst.mkdir()
    _write_project_version(inst, "1.2.3")

    assert updater.current_version(inst) == "1.2.3"


def test_verify_sha256_ok(tmp_path: Path) -> None:
    f = tmp_path / "x.tar.gz"
    f.write_bytes(b"hello world")
    digest = hashlib.sha256(b"hello world").hexdigest()
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(f"{digest}  x.tar.gz\n")
    updater.verify_sha256(f, sums)


def test_verify_sha256_mismatch(tmp_path: Path) -> None:
    f = tmp_path / "x.tar.gz"
    f.write_bytes(b"hello world")
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(f"{'0' * 64}  x.tar.gz\n")
    with pytest.raises(updater.UpdateError, match="SHA256 校验失败"):
        updater.verify_sha256(f, sums)


def test_verify_sha256_missing_entry(tmp_path: Path) -> None:
    f = tmp_path / "x.tar.gz"
    f.write_bytes(b"hi")
    sums = tmp_path / "SHA256SUMS"
    sums.write_text("deadbeef  other.tar.gz\n")
    with pytest.raises(updater.UpdateError, match="没有"):
        updater.verify_sha256(f, sums)


def test_extract_tarball_returns_top_dir(tmp_path: Path) -> None:
    tar = _build_release_tarball(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    top = updater.extract_tarball(tar, out)
    assert top.name == "sebastian-backend-v9.9.9"
    assert (top / "sebastian" / "__init__.py").exists()


def test_swap_in_replaces_managed_keeps_unmanaged(
    tmp_path: Path, _patch_backup_parent: Path
) -> None:
    inst = _make_install_dir(tmp_path)
    tar = _build_release_tarball(tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir()
    top = updater.extract_tarball(tar, staging)

    backup = updater.swap_in(top, inst)

    # New content moved in
    assert (inst / "sebastian" / "__init__.py").read_text() == "# new\n"
    assert (inst / "README.md").read_text() == "new readme\n"
    # Old content went to backup
    assert (backup / "sebastian" / "__init__.py").read_text() == "# old\n"
    assert (backup / "README.md").read_text() == "old readme\n"
    # Unmanaged stuff untouched
    assert (inst / ".env").read_text() == "SECRET=keep\n"
    assert (inst / ".venv" / "marker").read_text() == "dont touch\n"


def test_rollback_restores_old_files(tmp_path: Path, _patch_backup_parent: Path) -> None:
    inst = _make_install_dir(tmp_path)
    tar = _build_release_tarball(tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir()
    top = updater.extract_tarball(tar, staging)

    backup = updater.swap_in(top, inst)
    assert (inst / "README.md").read_text() == "new readme\n"

    updater.rollback(backup, inst)
    assert (inst / "README.md").read_text() == "old readme\n"
    assert (inst / "sebastian" / "__init__.py").read_text() == "# old\n"
    assert not backup.exists()


def test_swap_in_missing_entry_rolls_back(tmp_path: Path, _patch_backup_parent: Path) -> None:
    inst = _make_install_dir(tmp_path)
    # Build a broken staging dir missing LICENSE
    staging = tmp_path / "staging" / "broken"
    staging.mkdir(parents=True)
    (staging / "sebastian").mkdir()
    (staging / "sebastian" / "__init__.py").write_text("# new\n")
    (staging / "scripts").mkdir()
    (staging / "scripts" / "install.sh").write_text("new\n")
    (staging / "pyproject.toml").write_text("new\n")
    (staging / "README.md").write_text("new\n")
    (staging / "CHANGELOG.md").write_text("new\n")
    # LICENSE intentionally missing

    with pytest.raises(updater.UpdateError, match="缺少 LICENSE"):
        updater.swap_in(staging, inst)

    # Original install dir is intact
    assert (inst / "sebastian" / "__init__.py").read_text() == "# old\n"
    assert (inst / "README.md").read_text() == "old readme\n"


def test_prune_backups_keeps_newest(tmp_path: Path, _patch_backup_parent: Path) -> None:
    backup_root = _patch_backup_parent
    for i in range(5):
        b = backup_root / f"sebastian.bak.{i}"
        b.mkdir()
        os.utime(b, (i, i))
    updater.prune_backups(keep=2)
    remaining = sorted(p.name for p in backup_root.glob("sebastian.bak.*"))
    assert remaining == ["sebastian.bak.3", "sebastian.bak.4"]


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------


def test_run_update_already_latest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    inst = _make_install_dir(tmp_path)
    monkeypatch.setattr(updater, "resolve_install_dir", lambda: inst)
    monkeypatch.setattr(updater, "current_version", lambda install_dir: "1.2.3")
    monkeypatch.setattr(updater, "fetch_latest_tag", lambda: "v1.2.3")

    out: list[str] = []
    rc = updater.run_update(printer=out.append)
    assert rc == 0
    assert any("已经是最新版" in line for line in out)


def test_run_update_check_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    inst = _make_install_dir(tmp_path)
    monkeypatch.setattr(updater, "resolve_install_dir", lambda: inst)
    monkeypatch.setattr(updater, "current_version", lambda install_dir: "1.0.0")
    monkeypatch.setattr(updater, "fetch_latest_tag", lambda: "v1.1.0")

    out: list[str] = []
    rc = updater.run_update(check_only=True, printer=out.append)
    assert rc == 0
    assert any("可升级: 1.0.0 → 1.1.0" in line for line in out)


def test_run_update_full_flow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _patch_backup_parent: Path
) -> None:
    inst = _make_install_dir(tmp_path)
    tar = _build_release_tarball(tmp_path, version="9.9.9")
    sums_text = f"{updater._sha256(tar)}  {tar.name}\n"

    monkeypatch.setattr(updater, "resolve_install_dir", lambda: inst)
    monkeypatch.setattr(updater, "current_version", lambda install_dir: "0.0.1")
    monkeypatch.setattr(updater, "fetch_latest_tag", lambda: "v9.9.9")
    monkeypatch.setattr(updater, "_try_restart_daemon", lambda printer: None)

    def fake_download(url: str, dest: Path) -> None:
        if url.endswith(".tar.gz"):
            dest.write_bytes(tar.read_bytes())
        elif url.endswith("SHA256SUMS"):
            dest.write_text(sums_text)
        else:
            raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(updater, "_download", fake_download)
    monkeypatch.setattr(updater, "reinstall_editable", lambda install_dir: None)

    out: list[str] = []
    rc = updater.run_update(assume_yes=True, printer=out.append)
    assert rc == 0
    assert (inst / "README.md").read_text() == "new readme\n"
    assert (inst / ".env").read_text() == "SECRET=keep\n"
    # Backup cleaned up after success
    backup_root = _patch_backup_parent
    assert not list(backup_root.glob("sebastian.bak.*"))


def test_run_update_pip_failure_rolls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _patch_backup_parent: Path
) -> None:
    inst = _make_install_dir(tmp_path)
    tar = _build_release_tarball(tmp_path, version="9.9.9")
    sums_text = f"{updater._sha256(tar)}  {tar.name}\n"

    monkeypatch.setattr(updater, "resolve_install_dir", lambda: inst)
    monkeypatch.setattr(updater, "current_version", lambda install_dir: "0.0.1")
    monkeypatch.setattr(updater, "fetch_latest_tag", lambda: "v9.9.9")

    def fake_download(url: str, dest: Path) -> None:
        if url.endswith(".tar.gz"):
            dest.write_bytes(tar.read_bytes())
        else:
            dest.write_text(sums_text)

    monkeypatch.setattr(updater, "_download", fake_download)

    def boom(install_dir: Path) -> None:
        raise updater.UpdateError("pip exploded")

    monkeypatch.setattr(updater, "reinstall_editable", boom)

    out: list[str] = []
    rc = updater.run_update(assume_yes=True, printer=out.append)
    assert rc == 1
    # Rolled back to old contents
    assert (inst / "README.md").read_text() == "old readme\n"
    assert (inst / "sebastian" / "__init__.py").read_text() == "# old\n"
    # Backup cleaned up by rollback
    backup_root = _patch_backup_parent
    assert not list(backup_root.glob("sebastian.bak.*"))
