"""Sebastian self-update logic.

Replaces the current source tree under the installer-managed directory
(typically ``~/.sebastian/app``) with the latest GitHub release tarball.

Flow:
1. Resolve install dir from ``SEBASTIAN_INSTALL_DIR``, ``~/.sebastian/app``,
   or ``sebastian.__file__``.
2. Read current version from the install dir's ``pyproject.toml``.
3. Resolve latest tag via the ``releases/latest`` 302 redirect (avoids the
   60/hr unauthenticated api.github.com rate limit).
4. Download ``sebastian-backend-<tag>.tar.gz`` + ``SHA256SUMS`` to a tmp dir.
5. Verify SHA256.
6. Extract into a staging dir, then atomically swap top-level entries with
   the existing install dir, keeping a backup under ``~/.sebastian/run/update-backups/``
   for rollback.
7. Re-run ``pip install -e .`` inside the same interpreter so dependency
   changes take effect.
8. Roll back on any failure; on success delete the backup.
9. Auto-restart daemon if it was running.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.request
from collections.abc import Callable
from pathlib import Path
from urllib.error import URLError

REPO = "PhantomButler/Sebastian"
# Top-level entries that we own and may safely replace inside the install dir.
# Anything not in this list (.venv, .env, ~/.sebastian/data/, etc.)
# is left untouched.
MANAGED_ENTRIES = (
    "sebastian",
    "pyproject.toml",
    "scripts",
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
)
BACKUP_KEEP = 1


class UpdateError(RuntimeError):
    """Raised when an update step fails. Caller prints message and exits 1."""


# ---------------------------------------------------------------------------
# environment discovery
# ---------------------------------------------------------------------------


def resolve_install_dir() -> Path:
    """Return the directory that owns this `sebastian` package.

    For an installer-managed setup this is e.g. ``~/.sebastian/app``.
    """
    explicit = os.environ.get("SEBASTIAN_INSTALL_DIR")
    if explicit:
        return _validate_install_dir(Path(explicit).expanduser().resolve())

    default_install_dir = Path(os.environ.get("HOME", str(Path.home()))) / ".sebastian" / "app"
    if _is_install_dir(default_install_dir):
        return default_install_dir.resolve()

    import sebastian  # local import to avoid cycles

    pkg_file = Path(sebastian.__file__).resolve()
    # .../app/sebastian/__init__.py -> .../app
    install_dir = pkg_file.parents[1]
    return _validate_install_dir(install_dir)


def _is_install_dir(path: Path) -> bool:
    return (path / "pyproject.toml").exists() and (path / "sebastian").is_dir()


def _validate_install_dir(install_dir: Path) -> Path:
    if not _is_install_dir(install_dir):
        raise UpdateError(
            f"无法识别安装目录：{install_dir} 下没有 pyproject.toml 或 sebastian/。\n"
            "sebastian update 仅支持通过 bootstrap.sh / install.sh 安装的部署。"
        )
    return install_dir


def current_version(install_dir: Path) -> str:
    try:
        data = tomllib.loads((install_dir / "pyproject.toml").read_text())
        version = data["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as e:
        raise UpdateError(f"无法读取当前 sebastian 版本：{e}") from e
    if not isinstance(version, str) or not version:
        raise UpdateError("无法读取当前 sebastian 版本：pyproject.toml 中 version 无效")
    return version


# ---------------------------------------------------------------------------
# remote lookups
# ---------------------------------------------------------------------------


def fetch_latest_tag() -> str:
    """Resolve the latest release tag via the github.com 302 redirect."""
    url = f"https://github.com/{REPO}/releases/latest"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            final: str = resp.geturl()
    except URLError as e:
        raise UpdateError(f"查询最新版本失败：{e}") from e
    # final looks like https://github.com/<repo>/releases/tag/v0.2.1
    tag = final.rsplit("/", 1)[-1]
    if not tag or tag == "latest":
        raise UpdateError(f"无法解析最新 release tag（从 {final}）")
    return tag


def _download(url: str, dest: Path) -> None:
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, dest.open("wb") as f:
            shutil.copyfileobj(resp, f)
    except URLError as e:
        raise UpdateError(f"下载失败 {url}：{e}") from e


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_sha256(tarball: Path, sums_file: Path) -> None:
    expected: str | None = None
    for line in sums_file.read_text().splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and parts[1] == tarball.name:
            expected = parts[0]
            break
    if not expected:
        raise UpdateError(f"SHA256SUMS 中没有 {tarball.name} 的指纹")
    actual = _sha256(tarball)
    if actual != expected:
        raise UpdateError(
            f"SHA256 校验失败：期望 {expected}，实际 {actual}（已中止以防供应链污染）"
        )


# ---------------------------------------------------------------------------
# extraction + swap
# ---------------------------------------------------------------------------


def extract_tarball(tarball: Path, into: Path) -> Path:
    """Extract a github release tarball and return the (single) top-level dir."""
    with tarfile.open(tarball, "r:gz") as tf:
        tf.extractall(into, filter="data")
    children = [p for p in into.iterdir() if p.is_dir()]
    if len(children) != 1:
        raise UpdateError(f"tarball 顶层目录数量异常：{[p.name for p in children]}")
    return children[0]


def _backup_parent() -> Path:
    """Return run_dir/update-backups, creating it if needed."""
    from sebastian.config import settings

    d = settings.run_dir / "update-backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _backup_dir() -> Path:
    return _backup_parent() / f"sebastian.bak.{int(time.time())}"


def swap_in(staging: Path, install_dir: Path) -> Path:
    """Move managed entries from staging into install_dir, keeping a backup.

    Returns the backup directory path so callers can prune or rollback.
    """
    backup = _backup_dir()
    backup.mkdir(parents=True, exist_ok=False)

    moved: list[str] = []
    try:
        for name in MANAGED_ENTRIES:
            src = staging / name
            if not src.exists():
                # Tarball missing an entry we expect — refuse to proceed.
                raise UpdateError(f"新版本 tarball 缺少 {name}")
            dst = install_dir / name
            if dst.exists():
                shutil.move(str(dst), str(backup / name))
            shutil.move(str(src), str(dst))
            moved.append(name)
    except Exception:
        # Rollback partial move.
        for name in moved:
            dst = install_dir / name
            if dst.exists():
                shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
            bak_entry = backup / name
            if bak_entry.exists():
                shutil.move(str(bak_entry), str(dst))
        shutil.rmtree(backup, ignore_errors=True)
        raise
    return backup


def rollback(backup: Path, install_dir: Path) -> None:
    for name in MANAGED_ENTRIES:
        bak_entry = backup / name
        if not bak_entry.exists():
            continue
        dst = install_dir / name
        if dst.exists():
            shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
        shutil.move(str(bak_entry), str(dst))
    shutil.rmtree(backup, ignore_errors=True)


def prune_backups(keep: int = BACKUP_KEEP) -> None:
    backup_root = _backup_parent()
    backups = sorted(
        (p for p in backup_root.glob("sebastian.bak.*") if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in backups[keep:]:
        shutil.rmtree(old, ignore_errors=True)


# ---------------------------------------------------------------------------
# pip
# ---------------------------------------------------------------------------


def reinstall_editable(install_dir: Path) -> None:
    """Run ``pip install -e .`` inside the current interpreter."""
    cmd = [sys.executable, "-m", "pip", "install", "-e", str(install_dir)]
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        raise UpdateError("pip install -e . 失败，请查看上方输出")


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------


def _try_restart_daemon(printer: Callable[[str], None]) -> None:
    """If a Sebastian daemon is running, stop it and start a new one."""
    from sebastian.cli import daemon, service
    from sebastian.config import settings

    try:
        service_state = service.get_service_state()
    except service.ServiceError as e:
        printer(
            f"⚠ 系统服务状态检查失败：{e}。"
            "请手动运行 `sebastian service status` 或 `sebastian service restart`。"
        )
        return

    if service_state.installed and service_state.active:
        printer("→ 检测到 Sebastian 系统服务，正在重启...")
        try:
            service.restart()
        except service.ServiceError as e:
            printer(f"⚠ 系统服务重启失败：{e}，请手动运行 `sebastian service restart`。")
            return
        printer("✓ Sebastian 系统服务已重启")
        return

    if service_state.installed:
        printer("提示：检测到 Sebastian 系统服务已安装但未运行，请运行 `sebastian service start`。")
        return

    pf = daemon.pid_path(settings.run_dir)
    pid = daemon.read_pid(pf)
    if pid is None or not daemon.is_running(pid):
        printer("提示：未检测到后台进程，请手动运行 `sebastian serve`。")
        return

    printer(f"→ 检测到后台进程 (PID {pid})，正在重启...")
    daemon.stop_process(pf)

    cmd = [sys.executable, "-m", "sebastian.main", "serve", "--daemon"]
    proc = subprocess.run(cmd, check=False)
    if proc.returncode == 0:
        printer("✓ 后台进程已重启")
    else:
        printer("⚠ 自动重启失败，请手动运行 `sebastian serve -d`。")


def run_update(
    *,
    check_only: bool = False,
    force: bool = False,
    assume_yes: bool = False,
    printer: Callable[[str], None] = print,
    confirm: Callable[[str], str] = input,
) -> int:
    """Entry point used by the CLI. Returns process exit code."""
    install_dir = resolve_install_dir()
    cur = current_version(install_dir)
    printer(f"安装目录: {install_dir}")
    printer(f"当前版本: {cur}")

    printer("→ 查询最新版本...")
    tag = fetch_latest_tag()
    latest = tag.lstrip("v")
    printer(f"最新版本: {latest}")

    if latest == cur and not force:
        printer("✓ 已经是最新版。")
        return 0
    if check_only:
        printer(f"可升级: {cur} → {latest}（运行 `sebastian update` 应用升级）")
        return 0

    if not assume_yes:
        ans = confirm(f"将从 {cur} 升级到 {latest}，是否继续？[y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            printer("已取消。")
            return 1

    tar_name = f"sebastian-backend-{tag}.tar.gz"
    tar_url = f"https://github.com/{REPO}/releases/download/{tag}/{tar_name}"
    sums_url = f"https://github.com/{REPO}/releases/download/{tag}/SHA256SUMS"

    with tempfile.TemporaryDirectory(prefix="sebastian-update-") as tmp:
        tmp_path = Path(tmp)
        tarball = tmp_path / tar_name
        sums_file = tmp_path / "SHA256SUMS"

        printer(f"→ 下载 {tar_name} ...")
        _download(tar_url, tarball)
        printer("→ 下载 SHA256SUMS ...")
        _download(sums_url, sums_file)

        printer("→ 校验 SHA256 ...")
        verify_sha256(tarball, sums_file)
        printer("✓ SHA256 校验通过")

        printer("→ 解压新版本 ...")
        staging_root = tmp_path / "staging"
        staging_root.mkdir()
        staging = extract_tarball(tarball, staging_root)

        printer("→ 替换安装目录文件（旧版本会备份）...")
        backup = swap_in(staging, install_dir)

        try:
            printer("→ 重新安装依赖 ...")
            reinstall_editable(install_dir)
        except Exception as e:
            printer(f"✗ 升级失败，正在回滚：{e}")
            rollback(backup, install_dir)
            printer("已回滚到旧版本。")
            return 1

    # Upgrade succeeded — remove backup and prune old ones
    shutil.rmtree(backup, ignore_errors=True)
    prune_backups()

    printer("")
    printer(f"✓ 升级完成：{cur} → {latest}")

    # Auto-restart daemon if it was running
    _try_restart_daemon(printer)

    return 0
