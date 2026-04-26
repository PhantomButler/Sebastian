# Install Flow Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重组 `~/.sebastian/` 数据目录布局（`{app,data,logs,run}` 子目录），新增 `sebastian service` 子命令支持 systemd/launchd，重构 `install.sh` 不再阻塞，收紧 `bootstrap.sh` 升级路径。

**Architecture:** 单 PR 多 commit。先底层（config/migration）→ 中层（daemon/updater 路径调整）→ 上层（service CLI、install.sh、bootstrap.sh）→ 测试 → 文档同步。`SEBASTIAN_DATA_DIR` 环境变量语义不变（仍指 root），新增 `user_data_dir` / `logs_dir` / `run_dir` properties 区分用途。布局迁移在 `ensure_data_dir()` 中通过 `.layout-v2` 标记保证幂等。

**Tech Stack:** Python 3.12、Typer CLI、pydantic-settings、aiosqlite、bash、systemd user units、launchd LaunchAgents、pytest + pytest-asyncio。

**Spec:** [2026-04-26-install-flow-overhaul-design.md](../specs/2026-04-26-install-flow-overhaul-design.md)

---

## File Structure

**Created:**
- `sebastian/store/migration.py` — `migrate_layout_v2(data_root)` 函数 + 标记文件常量
- `sebastian/cli/service.py` — `service` Typer sub-app，含 install/uninstall/start/stop/status
- `sebastian/cli/service_templates.py` — systemd unit + launchd plist 模板渲染
- `tests/unit/test_layout_migration.py`
- `tests/unit/test_config_paths.py`
- `tests/unit/test_service_install.py`
- `tests/integration/test_updater_paths.py`

**Modified:**
- `sebastian/config/__init__.py` — 新增 `user_data_dir/logs_dir/run_dir`，重写依赖路径
- `sebastian/cli/daemon.py` — `pid_path` 形参重命名为 `run_dir`
- `sebastian/cli/updater.py` — `_backup_parent` 改用 `run_dir`，`_try_restart_daemon` 传 `run_dir`
- `sebastian/main.py` — 注册 `service` sub-app；`serve/stop/status` 用 `run_dir` 取 pid 路径
- `sebastian/gateway/app.py`（已 import `ensure_data_dir`，无需改）
- `scripts/install.sh` — 拆分首启与运行
- `scripts/dev.sh` — 提示文案微调
- `bootstrap.sh` — 目标非空保护
- `README.md`、`sebastian/config/README.md`、`CLAUDE.md` — 文档同步

---

## Task 1: 配置层引入 user_data_dir / logs_dir / run_dir

**Files:**
- Modify: `sebastian/config/__init__.py`
- Test: `tests/unit/test_config_paths.py`

- [ ] **Step 1: Write failing test for new config properties**

Create `tests/unit/test_config_paths.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from sebastian.config import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(sebastian_data_dir=str(tmp_path))


def test_data_dir_remains_root(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    assert s.data_dir == tmp_path.resolve()


def test_user_data_dir_is_data_subdir(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    assert s.user_data_dir == (tmp_path / "data").resolve()


def test_logs_dir(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    assert s.logs_dir == (tmp_path / "logs").resolve()


def test_run_dir(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    assert s.run_dir == (tmp_path / "run").resolve()


def test_database_url_uses_user_data_dir(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    assert s.database_url == f"sqlite+aiosqlite:///{tmp_path.resolve()}/data/sebastian.db"


def test_workspace_dir_under_user_data(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    assert s.workspace_dir == (tmp_path / "data" / "workspace").resolve()


def test_extensions_dir_under_user_data(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    assert s.extensions_dir == (tmp_path / "data" / "extensions").resolve()


def test_resolved_secret_key_under_user_data(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    assert s.resolved_secret_key_path() == (tmp_path / "data" / "secret.key").resolve()


def test_sessions_dir_removed() -> None:
    # 显式断言旧属性已移除
    assert not hasattr(Settings, "sessions_dir")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_config_paths.py -v`
Expected: 多条 FAIL（属性不存在或路径错误）

- [ ] **Step 3: Refactor `sebastian/config/__init__.py`**

Replace the body of `Settings` properties section + `ensure_data_dir`:

```python
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""

    sebastian_owner_name: str = "Owner"
    sebastian_data_dir: str = str(Path.home() / ".sebastian")
    sebastian_sandbox_enabled: bool = False
    sebastian_memory_enabled: bool = True

    sebastian_gateway_host: str = "0.0.0.0"
    sebastian_gateway_port: int = 8823

    sebastian_jwt_algorithm: str = "HS256"
    sebastian_jwt_expire_minutes: int = 43200

    sebastian_secret_key_path: str = ""
    sebastian_db_url: str = ""

    sebastian_model: str = "claude-opus-4-6"
    llm_max_tokens: int = 32000

    sebastian_log_llm_stream: bool = False
    sebastian_log_sse: bool = False

    @property
    def data_dir(self) -> Path:
        """Root install / data directory (~/.sebastian by default)."""
        return Path(self.sebastian_data_dir).expanduser().resolve()

    @property
    def user_data_dir(self) -> Path:
        """User data subdir (db, secret.key, workspace, extensions)."""
        return self.data_dir / "data"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def run_dir(self) -> Path:
        return self.data_dir / "run"

    @property
    def database_url(self) -> str:
        if self.sebastian_db_url:
            return self.sebastian_db_url
        return f"sqlite+aiosqlite:///{self.user_data_dir}/sebastian.db"

    @property
    def extensions_dir(self) -> Path:
        return self.user_data_dir / "extensions"

    @property
    def skills_extensions_dir(self) -> Path:
        return self.extensions_dir / "skills"

    @property
    def agents_extensions_dir(self) -> Path:
        return self.extensions_dir / "agents"

    @property
    def workspace_dir(self) -> Path:
        return self.user_data_dir / "workspace"

    def resolved_secret_key_path(self) -> Path:
        if self.sebastian_secret_key_path:
            return Path(self.sebastian_secret_key_path).expanduser()
        return self.user_data_dir / "secret.key"


settings = Settings()


def ensure_data_dir() -> None:
    """Create required data directory structure (idempotent).

    Runs the layout-v2 migration first to upgrade legacy installs.
    """
    from sebastian.store.migration import migrate_layout_v2

    migrate_layout_v2(settings.data_dir)

    for sub in (
        settings.user_data_dir / "extensions" / "skills",
        settings.user_data_dir / "extensions" / "agents",
        settings.user_data_dir / "workspace",
        settings.logs_dir,
        settings.run_dir,
    ):
        sub.mkdir(parents=True, exist_ok=True)


__all__ = ["Settings", "settings", "ensure_data_dir"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_config_paths.py -v`
Expected: PASS（migration 模块还不存在，但 `ensure_data_dir` 没被这些测试调用，应该全绿；如有 import 错误，先在 Task 2 之后再回头跑）

如果出现 `ModuleNotFoundError: sebastian.store.migration`，临时把 `ensure_data_dir` 的 import 注释掉，跑过这一组 test 后在下一个 task 修复。

- [ ] **Step 5: Commit**

```bash
git add sebastian/config/__init__.py tests/unit/test_config_paths.py
git commit -m "refactor(config): 引入 user_data_dir/logs_dir/run_dir

- data_dir 仍指 root，向后兼容 SEBASTIAN_DATA_DIR
- 新增 user_data_dir/logs_dir/run_dir 三个 property
- database_url/extensions_dir/workspace_dir/secret.key 全部下移到 user_data_dir
- 删除已废弃的 sessions_dir
- ensure_data_dir 调用 migrate_layout_v2（下个 commit 实现）

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: 布局迁移 migrate_layout_v2

**Files:**
- Create: `sebastian/store/migration.py`
- Test: `tests/unit/test_layout_migration.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_layout_migration.py`:

```python
from __future__ import annotations

from pathlib import Path

from sebastian.store.migration import LAYOUT_MARKER, migrate_layout_v2


def test_fresh_install_creates_skeleton(tmp_path: Path) -> None:
    migrate_layout_v2(tmp_path)
    assert (tmp_path / LAYOUT_MARKER).read_text().strip() == "2"
    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "logs").is_dir()
    assert (tmp_path / "run").is_dir()


def test_marker_present_is_noop(tmp_path: Path) -> None:
    (tmp_path / LAYOUT_MARKER).write_text("2\n")
    sentinel = tmp_path / "sebastian.db"
    sentinel.write_text("legacy")  # 应该不被搬走
    migrate_layout_v2(tmp_path)
    assert sentinel.exists()
    assert not (tmp_path / "data" / "sebastian.db").exists()


def test_v1_layout_migrated(tmp_path: Path) -> None:
    # 模拟旧布局
    (tmp_path / "sebastian.db").write_text("db")
    (tmp_path / "secret.key").write_text("secret")
    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "f.txt").write_text("data")
    (tmp_path / "extensions").mkdir()
    (tmp_path / "extensions" / "skills").mkdir()
    (tmp_path / "sebastian.pid").write_text("12345")
    (tmp_path / "backups").mkdir()
    (tmp_path / "backups" / "old").write_text("rollback")
    (tmp_path / "sessions").mkdir()
    (tmp_path / "sessions" / "junk").write_text("legacy")

    migrate_layout_v2(tmp_path)

    # 用户数据进 data/
    assert (tmp_path / "data" / "sebastian.db").read_text() == "db"
    assert (tmp_path / "data" / "secret.key").read_text() == "secret"
    assert (tmp_path / "data" / "workspace" / "f.txt").read_text() == "data"
    assert (tmp_path / "data" / "extensions" / "skills").is_dir()

    # pid 进 run/
    assert (tmp_path / "run" / "sebastian.pid").read_text() == "12345"

    # 旧 update 回滚目录进 run/update-backups
    assert (tmp_path / "run" / "update-backups" / "old").read_text() == "rollback"

    # sessions 被删
    assert not (tmp_path / "sessions").exists()

    # 旧路径不再存在
    assert not (tmp_path / "sebastian.db").exists()
    assert not (tmp_path / "secret.key").exists()
    assert not (tmp_path / "workspace").exists()
    assert not (tmp_path / "extensions").exists()
    assert not (tmp_path / "sebastian.pid").exists()
    assert not (tmp_path / "backups").exists()

    # 标记落地
    assert (tmp_path / LAYOUT_MARKER).read_text().strip() == "2"


def test_partial_v1_layout(tmp_path: Path) -> None:
    """只有部分旧文件存在，其余项不应该报错。"""
    (tmp_path / "sebastian.db").write_text("db")
    # 没有 secret.key / workspace / extensions / pid / backups
    migrate_layout_v2(tmp_path)
    assert (tmp_path / "data" / "sebastian.db").read_text() == "db"
    assert (tmp_path / LAYOUT_MARKER).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_layout_migration.py -v`
Expected: FAIL with `ModuleNotFoundError: sebastian.store.migration`

- [ ] **Step 3: Implement `sebastian/store/migration.py`**

```python
"""Filesystem layout migration for Sebastian data directory.

Schema versions:
- v1 (pre-2026-04): everything flat under ~/.sebastian/
- v2: split into {app, data, logs, run} subdirs

The marker file ``.layout-v2`` records the current schema. Migration is
idempotent: present marker → no-op.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

LAYOUT_MARKER = ".layout-v2"
CURRENT_SCHEMA = "2"

# 用户数据：从 root 搬到 data/
_USER_DATA_ENTRIES = ("sebastian.db", "secret.key", "workspace", "extensions")


def migrate_layout_v2(data_root: Path) -> None:
    """Idempotently upgrade a legacy v1 layout to v2 in-place.

    Safe to call on every startup. No-op once the marker is present.
    """
    marker = data_root / LAYOUT_MARKER
    if marker.exists():
        return

    data_root.mkdir(parents=True, exist_ok=True)

    legacy_db = data_root / "sebastian.db"
    if not legacy_db.exists() and not _has_any_legacy_artifact(data_root):
        # Fresh install — just create the skeleton.
        _ensure_v2_dirs(data_root)
        marker.write_text(f"{CURRENT_SCHEMA}\n")
        return

    logger.info("Detected v1 layout under %s, migrating to v2...", data_root)
    _ensure_v2_dirs(data_root)

    # User data → data/
    user_data = data_root / "data"
    for name in _USER_DATA_ENTRIES:
        src = data_root / name
        if src.exists():
            shutil.move(str(src), str(user_data / name))

    # PID file → run/
    pid_src = data_root / "sebastian.pid"
    if pid_src.exists():
        shutil.move(str(pid_src), str(data_root / "run" / "sebastian.pid"))

    # Legacy update-rollback dir → run/update-backups/
    legacy_backups = data_root / "backups"
    if legacy_backups.exists():
        shutil.move(str(legacy_backups), str(data_root / "run" / "update-backups"))

    # Deprecated sessions dir
    sessions = data_root / "sessions"
    if sessions.exists():
        shutil.rmtree(sessions)

    marker.write_text(f"{CURRENT_SCHEMA}\n")
    logger.info("Layout migration v2 complete")


def _ensure_v2_dirs(data_root: Path) -> None:
    (data_root / "data").mkdir(exist_ok=True)
    (data_root / "logs").mkdir(exist_ok=True)
    (data_root / "run").mkdir(exist_ok=True)


def _has_any_legacy_artifact(data_root: Path) -> bool:
    for name in (*_USER_DATA_ENTRIES, "sebastian.pid", "backups", "sessions"):
        if (data_root / name).exists():
            return True
    return False
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_layout_migration.py tests/unit/test_config_paths.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/store/migration.py tests/unit/test_layout_migration.py
git commit -m "feat(store): layout v2 自动迁移

- migrate_layout_v2 在 ensure_data_dir 中调用，幂等
- v1 → v2：user data 进 data/，pid 进 run/，旧 backups 进 run/update-backups/
- 已废弃的 sessions/ 目录顺手清理
- .layout-v2 标记文件保证幂等

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: daemon pid 与 updater 路径迁移到 run_dir

**Files:**
- Modify: `sebastian/cli/daemon.py:8-10`
- Modify: `sebastian/main.py` (4 处 pid_path 调用)
- Modify: `sebastian/cli/updater.py` (`_backup_parent` 与 `_try_restart_daemon`)
- Test: `tests/integration/test_updater_paths.py`

- [ ] **Step 1: Write failing test for updater backup path**

Create `tests/integration/test_updater_paths.py`:

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


def test_backup_parent_under_run_dir(tmp_path: Path) -> None:
    from sebastian.cli import updater
    from sebastian.config import Settings

    fake_settings = Settings(sebastian_data_dir=str(tmp_path))
    with patch.object(updater, "settings", fake_settings, create=True), patch(
        "sebastian.config.settings", fake_settings
    ):
        backup = updater._backup_parent()
    assert backup == (tmp_path / "run" / "update-backups").resolve()
    assert backup.is_dir()
```

> 说明：`_backup_parent` 当前从 `sebastian.config import settings` 取，所以测试 patch `sebastian.config.settings`。

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_updater_paths.py -v`
Expected: FAIL（路径仍是 `~/.sebastian/backups`）

- [ ] **Step 3: Update `sebastian/cli/daemon.py`**

Rename parameter `data_dir` → `run_dir`:

```python
def pid_path(run_dir: Path) -> Path:
    """Return the standard PID file path inside run_dir."""
    return run_dir / "sebastian.pid"
```

- [ ] **Step 4: Update all `pid_path(...)` call sites**

In `sebastian/main.py`, replace 4 occurrences:

```python
# main.py:47 (serve daemon branch)
pf = pid_path(settings.run_dir)

# main.py:82 (stop)
pf = pid_path(settings.run_dir)

# main.py:95 (status)
pf = pid_path(settings.run_dir)
```

In `sebastian/cli/updater.py:266`:

```python
pf = pid_path(settings.run_dir)
```

- [ ] **Step 5: Update `_backup_parent` in `sebastian/cli/updater.py`**

Replace lines 175-179:

```python
def _backup_parent() -> Path:
    """Return run_dir/update-backups, creating it if needed."""
    from sebastian.config import settings

    d = settings.run_dir / "update-backups"
    d.mkdir(parents=True, exist_ok=True)
    return d
```

Also update the module docstring at the top of `updater.py` line 15:

```python
   the existing install dir, keeping a backup under ``~/.sebastian/run/update-backups/``
```

- [ ] **Step 6: Run all affected tests**

Run: `pytest tests/integration/test_updater_paths.py tests/unit/test_layout_migration.py tests/unit/test_config_paths.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add sebastian/cli/daemon.py sebastian/main.py sebastian/cli/updater.py tests/integration/test_updater_paths.py
git commit -m "refactor(daemon,updater): pid 与回滚目录迁移到 run_dir

- daemon.pid_path 形参重命名为 run_dir
- main.py 三处调用改用 settings.run_dir
- updater._backup_parent 落到 run_dir/update-backups
- updater 重启 daemon 改用 settings.run_dir

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: service CLI 模板渲染

**Files:**
- Create: `sebastian/cli/service_templates.py`
- Test: `tests/unit/test_service_install.py`（先建文件，本任务只覆盖模板渲染）

- [ ] **Step 1: Write failing test for template rendering**

Create `tests/unit/test_service_install.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from sebastian.cli.service_templates import (
    render_launchd_plist,
    render_systemd_unit,
)


def test_systemd_unit_contains_exec_start() -> None:
    unit = render_systemd_unit()
    assert "ExecStart=%h/.sebastian/app/.venv/bin/sebastian serve" in unit
    assert "Restart=on-failure" in unit
    assert "StandardOutput=append:%h/.sebastian/logs/service.out.log" in unit
    assert "StandardError=append:%h/.sebastian/logs/service.err.log" in unit
    assert "WantedBy=default.target" in unit


def test_launchd_plist_renders_home(tmp_path: Path) -> None:
    home = Path("/Users/eric")
    plist = render_launchd_plist(home=home)
    assert "<key>Label</key><string>com.sebastian</string>" in plist
    assert "<string>/Users/eric/.sebastian/app/.venv/bin/sebastian</string>" in plist
    assert "<string>/Users/eric/.sebastian/logs/service.out.log</string>" in plist
    assert "<key>RunAtLoad</key><true/>" in plist
    assert "<key>KeepAlive</key><true/>" in plist
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_service_install.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `sebastian/cli/service_templates.py`**

```python
"""Service unit / plist template rendering.

systemd uses %h for $HOME at runtime; launchd plists do not support
variable expansion, so HOME is rendered into the plist content directly.
"""

from __future__ import annotations

from pathlib import Path

SYSTEMD_UNIT_TEMPLATE = """\
[Unit]
Description=Sebastian personal AI butler
After=network-online.target

[Service]
Type=simple
ExecStart=%h/.sebastian/app/.venv/bin/sebastian serve
Restart=on-failure
RestartSec=5
StandardOutput=append:%h/.sebastian/logs/service.out.log
StandardError=append:%h/.sebastian/logs/service.err.log

[Install]
WantedBy=default.target
"""

_LAUNCHD_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.sebastian</string>
  <key>ProgramArguments</key>
  <array>
    <string>{home}/.sebastian/app/.venv/bin/sebastian</string>
    <string>serve</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{home}/.sebastian/logs/service.out.log</string>
  <key>StandardErrorPath</key><string>{home}/.sebastian/logs/service.err.log</string>
</dict>
</plist>
"""


def render_systemd_unit() -> str:
    return SYSTEMD_UNIT_TEMPLATE


def render_launchd_plist(*, home: Path) -> str:
    return _LAUNCHD_PLIST_TEMPLATE.format(home=str(home))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_service_install.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/cli/service_templates.py tests/unit/test_service_install.py
git commit -m "feat(cli): systemd unit + launchd plist 模板

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: service install/uninstall/start/stop/status 子命令

**Files:**
- Create: `sebastian/cli/service.py`
- Modify: `sebastian/main.py`（注册 `service` sub-app）
- Modify: `tests/unit/test_service_install.py`（追加 install/uninstall 测试）

- [ ] **Step 1: Append failing tests for install/uninstall behavior**

Append to `tests/unit/test_service_install.py`:

```python
from unittest.mock import MagicMock, patch


@pytest.fixture
def linux_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("sebastian.cli.service.sys.platform", "linux")
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    return fake_home


@pytest.fixture
def macos_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("sebastian.cli.service.sys.platform", "darwin")
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    return fake_home


def test_install_writes_systemd_unit_on_linux(linux_env: Path) -> None:
    from sebastian.cli import service

    with patch.object(service.subprocess, "run", return_value=MagicMock(returncode=0)) as run:
        service.install()

    unit = linux_env / ".config/systemd/user/sebastian.service"
    assert unit.is_file()
    assert "Sebastian personal AI butler" in unit.read_text()
    # 第一次调用应该是 systemctl --user daemon-reload
    cmds = [call.args[0] for call in run.call_args_list]
    assert ["systemctl", "--user", "daemon-reload"] in cmds
    assert ["systemctl", "--user", "enable", "--now", "sebastian.service"] in cmds


def test_install_writes_plist_on_macos(macos_env: Path) -> None:
    from sebastian.cli import service

    with patch.object(service.subprocess, "run", return_value=MagicMock(returncode=0)) as run:
        service.install()

    plist = macos_env / "Library/LaunchAgents/com.sebastian.plist"
    assert plist.is_file()
    assert "com.sebastian" in plist.read_text()
    cmds = [call.args[0] for call in run.call_args_list]
    assert ["launchctl", "load", "-w", str(plist)] in cmds


def test_install_refuses_when_unit_exists(linux_env: Path) -> None:
    from sebastian.cli import service

    unit = linux_env / ".config/systemd/user/sebastian.service"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text("[stale]")

    with pytest.raises(service.ServiceError, match="已存在"):
        service.install()


def test_uninstall_removes_unit_on_linux(linux_env: Path) -> None:
    from sebastian.cli import service

    unit = linux_env / ".config/systemd/user/sebastian.service"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text("[old]")

    with patch.object(service.subprocess, "run", return_value=MagicMock(returncode=0)):
        service.uninstall()

    assert not unit.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_service_install.py -v`
Expected: FAIL on the new tests (ModuleNotFoundError or ServiceError missing)

- [ ] **Step 3: Implement `sebastian/cli/service.py`**

```python
"""``sebastian service`` subcommands — install/uninstall/start/stop/status.

User-level systemd units (Linux) and launchd LaunchAgents (macOS). No sudo.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer

from sebastian.cli.service_templates import render_launchd_plist, render_systemd_unit

app = typer.Typer(name="service", help="作为后台系统服务管理 Sebastian")


class ServiceError(RuntimeError):
    """Raised when a service operation fails."""


# ---------------------------------------------------------------------------
# path resolution
# ---------------------------------------------------------------------------


def _systemd_unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / "sebastian.service"


def _launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "com.sebastian.plist"


def _platform_unsupported() -> ServiceError:
    return ServiceError(f"unsupported platform: {sys.platform}")


# ---------------------------------------------------------------------------
# core operations (no Typer)
# ---------------------------------------------------------------------------


def install() -> None:
    if sys.platform.startswith("linux"):
        _install_systemd()
    elif sys.platform == "darwin":
        _install_launchd()
    else:
        raise _platform_unsupported()


def uninstall() -> None:
    if sys.platform.startswith("linux"):
        _uninstall_systemd()
    elif sys.platform == "darwin":
        _uninstall_launchd()
    else:
        raise _platform_unsupported()


def start() -> None:
    if sys.platform.startswith("linux"):
        _run(["systemctl", "--user", "start", "sebastian.service"])
    elif sys.platform == "darwin":
        _run(["launchctl", "start", "com.sebastian"])
    else:
        raise _platform_unsupported()


def stop() -> None:
    if sys.platform.startswith("linux"):
        _run(["systemctl", "--user", "stop", "sebastian.service"])
    elif sys.platform == "darwin":
        _run(["launchctl", "stop", "com.sebastian"])
    else:
        raise _platform_unsupported()


def status() -> str:
    if sys.platform.startswith("linux"):
        return _status_systemd()
    if sys.platform == "darwin":
        return _status_launchd()
    raise _platform_unsupported()


# ---------------------------------------------------------------------------
# systemd
# ---------------------------------------------------------------------------


def _install_systemd() -> None:
    unit = _systemd_unit_path()
    if unit.exists():
        raise ServiceError(f"{unit} 已存在，请先 sebastian service uninstall")
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(render_systemd_unit())
    _run(["systemctl", "--user", "daemon-reload"])
    _run(["systemctl", "--user", "enable", "--now", "sebastian.service"])
    _check_linger()


def _uninstall_systemd() -> None:
    unit = _systemd_unit_path()
    # 停服务（已停或不存在不算错）
    subprocess.run(
        ["systemctl", "--user", "disable", "--now", "sebastian.service"],
        check=False,
    )
    if unit.exists():
        unit.unlink()
        _run(["systemctl", "--user", "daemon-reload"])


def _status_systemd() -> str:
    proc = subprocess.run(
        ["systemctl", "--user", "is-active", "sebastian.service"],
        capture_output=True,
        text=True,
        check=False,
    )
    state = proc.stdout.strip() or proc.stderr.strip()
    return f"systemd user service: {state}"


def _check_linger() -> None:
    """Warn user if user-level linger is disabled (service won't survive logout)."""
    import os

    user = os.environ.get("USER", "")
    proc = subprocess.run(
        ["loginctl", "show-user", user, "-P", "Linger"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.stdout.strip().lower() != "yes":
        typer.echo(
            "\n⚠ 当前用户未开启 linger，重启后服务不会自动拉起。如需开机自启请执行：\n"
            f"    sudo loginctl enable-linger {user}\n"
        )


# ---------------------------------------------------------------------------
# launchd
# ---------------------------------------------------------------------------


def _install_launchd() -> None:
    plist = _launchd_plist_path()
    if plist.exists():
        raise ServiceError(f"{plist} 已存在，请先 sebastian service uninstall")
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(render_launchd_plist(home=Path.home()))
    _run(["launchctl", "load", "-w", str(plist)])


def _uninstall_launchd() -> None:
    plist = _launchd_plist_path()
    if plist.exists():
        subprocess.run(["launchctl", "unload", "-w", str(plist)], check=False)
        plist.unlink()


def _status_launchd() -> str:
    proc = subprocess.run(
        ["launchctl", "list", "com.sebastian"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return "launchd: not loaded"
    return f"launchd:\n{proc.stdout}"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        raise ServiceError(f"命令失败: {' '.join(cmd)} (exit {proc.returncode})")


def _tail_log(log_path: Path, lines: int = 20) -> str:
    if not log_path.exists():
        return ""
    try:
        with log_path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 8192)
            f.seek(size - chunk)
            tail = f.read().decode("utf-8", errors="replace").splitlines()
        return "\n".join(tail[-lines:])
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Typer commands
# ---------------------------------------------------------------------------


@app.command("install")
def cmd_install() -> None:
    """注册 Sebastian 为系统服务（开机自启 + 异常重启）。"""
    try:
        install()
    except ServiceError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(code=1) from e
    typer.echo("✓ 已安装并启动 Sebastian 系统服务")


@app.command("uninstall")
def cmd_uninstall() -> None:
    """卸载 Sebastian 系统服务。"""
    try:
        uninstall()
    except ServiceError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(code=1) from e
    typer.echo("✓ 已卸载 Sebastian 系统服务")


@app.command("start")
def cmd_start() -> None:
    try:
        start()
    except ServiceError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command("stop")
def cmd_stop() -> None:
    try:
        stop()
    except ServiceError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command("status")
def cmd_status() -> None:
    """显示服务状态及最近日志。"""
    from sebastian.config import settings

    try:
        info = status()
    except ServiceError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(code=1) from e
    typer.echo(info)
    tail = _tail_log(settings.logs_dir / "service.err.log")
    if tail:
        typer.echo("\n--- 最近 service.err.log ---")
        typer.echo(tail)
```

- [ ] **Step 4: Register sub-app in `sebastian/main.py`**

Add after line 9 (`app = typer.Typer(...)`):

```python
from sebastian.cli.service import app as service_app

app.add_typer(service_app, name="service")
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_service_install.py -v`
Expected: ALL PASS

Manual smoke check:

```bash
sebastian service --help
```

Expected: subcommands install/uninstall/start/stop/status listed.

- [ ] **Step 6: Commit**

```bash
git add sebastian/cli/service.py sebastian/main.py tests/unit/test_service_install.py
git commit -m "feat(cli): sebastian service install/uninstall/start/stop/status

- Linux: ~/.config/systemd/user/sebastian.service (user-level，无需 sudo)
- macOS: ~/Library/LaunchAgents/com.sebastian.plist
- install 检测同名 unit/plist 存在则报错引导先 uninstall
- Linux 安装后检测 loginctl Linger 状态，未开则提示用户手动 enable-linger
- status 输出服务状态 + tail service.err.log

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: install.sh 拆分 + dev.sh 提示同步

**Files:**
- Modify: `scripts/install.sh`
- Modify: `scripts/dev.sh`

- [ ] **Step 1: Rewrite `scripts/install.sh`**

Replace the file with:

```bash
#!/usr/bin/env bash
# Sebastian installer — runs inside an already-extracted source tree.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

color_red()  { printf "\033[31m%s\033[0m\n" "$*"; }
color_grn()  { printf "\033[32m%s\033[0m\n" "$*"; }
color_ylw()  { printf "\033[33m%s\033[0m\n" "$*"; }
color_dim()  { printf "\033[90m%s\033[0m\n" "$*"; }

# 1. OS check
OS="$(uname -s)"
case "$OS" in
  Darwin|Linux) ;;
  *) color_red "❌ 不支持的操作系统: $OS (仅支持 macOS / Linux)"; exit 1 ;;
esac

# 2. Python 3.12+
if ! command -v python3 >/dev/null 2>&1; then
  color_red "❌ 未找到 python3。请先安装 Python 3.12 或更高版本。"
  exit 1
fi

PY_VERSION="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PY_MAJOR="$(echo "$PY_VERSION" | cut -d. -f1)"
PY_MINOR="$(echo "$PY_VERSION" | cut -d. -f2)"
if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 12 ]]; }; then
  color_red "❌ Python 版本过低（当前 ${PY_VERSION}），需要 >= 3.12"
  exit 1
fi
color_grn "✓ Python $PY_VERSION"

# 3. venv
if [[ ! -f .venv/bin/activate ]]; then
  color_ylw "→ 创建/修复虚拟环境 .venv"
  python3 -m venv .venv
fi
if [[ ! -f .venv/bin/activate ]]; then
  color_red "❌ 虚拟环境创建失败：缺少 .venv/bin/activate"
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
color_grn "✓ 已激活 .venv"

# 4. 安装依赖
color_ylw "→ 安装依赖（可能需要几分钟）"
pip install --upgrade pip >/dev/null
pip install -e .
color_grn "✓ 依赖安装完成"

# 5. 数据目录定位
DATA_ROOT="${SEBASTIAN_DATA_DIR:-$HOME/.sebastian}"
USER_DATA_DIR="${DATA_ROOT}/data"

# 6. 首启向导（数据库不存在则进）
if [[ ! -f "${USER_DATA_DIR}/sebastian.db" ]]; then
  color_ylw "→ 进入初始化向导..."
  if [[ "$OS" == "Linux" && -z "${DISPLAY:-}" ]]; then
    sebastian init --headless
  else
    # 启动 serve（serve 启动时会唤起 web wizard 并在完成后自动退出）
    sebastian serve
  fi
else
  color_grn "✓ 检测到已初始化数据，跳过向导"
fi

# 7. 询问是否注册服务
echo ""
read -r -p "是否注册为开机自启服务（systemd / launchd）？[y/N] " ANS
case "${ANS:-N}" in
  y|Y|yes|YES)
    color_ylw "→ 安装系统服务..."
    sebastian service install
    color_grn "✓ 服务已注册"
    REGISTERED=1
    ;;
  *)
    color_dim "已跳过。稍后可执行：sebastian service install"
    REGISTERED=0
    ;;
esac

# 8. 退出指引
echo ""
color_grn "============================================"
color_grn "  Sebastian 安装完成"
color_grn "============================================"
if [[ "${REGISTERED:-0}" -eq 1 ]]; then
  color_dim "  服务状态:  sebastian service status"
  color_dim "  停止服务:  sebastian service stop"
else
  color_dim "  启动服务:  sebastian serve"
  color_dim "  注册服务:  sebastian service install"
fi
color_dim "  日志目录:  ${DATA_ROOT}/logs/"
color_dim "  Android 配置:"
color_dim "    模拟器:  http://10.0.2.2:8823"
color_dim "    真机:    http://<本机局域网IP>:8823"
color_grn "============================================"
```

- [ ] **Step 2: Update `scripts/dev.sh` first-time prompt**

In `scripts/dev.sh`, replace the首次初始化提示 block (lines 41-47):

```bash
# ── 首次初始化提示 ──
if [[ ! -d "${SEBASTIAN_DATA_DIR}" ]] || [[ ! -f "${SEBASTIAN_DATA_DIR}/data/sebastian.db" ]]; then
  color_ylw "→ 首次使用开发数据目录: ${SEBASTIAN_DATA_DIR}"
  color_dim "  数据将分布在 ${SEBASTIAN_DATA_DIR}/{app,data,logs,run} 子目录"
  color_ylw "  启动后会进入初始化向导，需要设置 owner 账号和 LLM Provider"
  color_dim "  Android 模拟器连接地址: http://10.0.2.2:${SEBASTIAN_GATEWAY_PORT}"
  echo ""
fi
```

- [ ] **Step 3: Smoke test install.sh skip path**

```bash
shellcheck scripts/install.sh scripts/dev.sh
```

Expected: 无 error（warning 可接受）。如果系统没装 shellcheck，跳过此步并在 PR 描述中标注待用户验证。

- [ ] **Step 4: Commit**

```bash
git add scripts/install.sh scripts/dev.sh
git commit -m "refactor(install,dev): 拆分首启与运行，dev.sh 提示同步

- install.sh 不再 exec sebastian serve，wizard 完成后退出
- 询问用户是否注册为系统服务（默认 N）
- headless 服务器（无 \$DISPLAY 的 Linux）走 sebastian init --headless
- dev.sh 首次提示文案体现新布局子目录

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: bootstrap.sh 收紧

**Files:**
- Modify: `bootstrap.sh`

- [ ] **Step 1: Add target dir guard**

In `bootstrap.sh`, find the section starting with `# 5. 解压` (around line 60). Replace the lines from the section header through the `tar xzf` line with:

```bash
# 5. 目标目录保护
if [[ -d "$INSTALL_DIR" && -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
  if [[ -f "$INSTALL_DIR/pyproject.toml" ]]; then
    color_red "❌ 检测到 $INSTALL_DIR 已有 Sebastian 安装"
    color_red "   全新安装请先删除该目录；升级请使用："
    color_red "       cd $INSTALL_DIR && sebastian update"
    exit 1
  else
    color_red "❌ $INSTALL_DIR 非空但不是 Sebastian 安装目录，已中止以防覆盖"
    exit 1
  fi
fi

# 6. 解压
color_ylw "→ 解压到 $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
tar xzf "${TMPDIR}/${TAR_NAME}" -C "$INSTALL_DIR" --strip-components=1
```

(Renumber subsequent comment markers if any.)

- [ ] **Step 2: Smoke test**

```bash
shellcheck bootstrap.sh
```

Expected: 无 error。

- [ ] **Step 3: Commit**

```bash
git add bootstrap.sh
git commit -m "fix(bootstrap): 目标非空时拒绝覆盖

- 检测 INSTALL_DIR/pyproject.toml 存在 → 引导用户跑 sebastian update
- 非空但不是 Sebastian 目录 → 直接中止以防误覆盖
- 全新空目录路径不变

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: 全量回归 + 文档同步

**Files:**
- Modify: `README.md`
- Modify: `sebastian/config/README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run full test suite**

Run:

```bash
pytest tests/unit/test_layout_migration.py tests/unit/test_config_paths.py tests/unit/test_service_install.py tests/integration/test_updater_paths.py -v
```

Expected: ALL PASS.

Then run the broader suite to catch regressions:

```bash
pytest tests/unit -x --ignore=tests/unit/test_layout_migration.py --ignore=tests/unit/test_config_paths.py --ignore=tests/unit/test_service_install.py
```

Expected: PASS（已有测试不应被路径改动破坏）。如有 fail，多半是某个测试硬编码 `data_dir/sebastian.db` 之类，按相同规则改成 `user_data_dir/sebastian.db` 即可。

- [ ] **Step 2: Run lint**

```bash
ruff check sebastian/ tests/
ruff format --check sebastian/ tests/
mypy sebastian/cli/service.py sebastian/cli/service_templates.py sebastian/store/migration.py sebastian/config/__init__.py
```

Expected: ALL PASS。如 ruff format 抱怨格式，跑 `ruff format sebastian/ tests/` 修复。

- [ ] **Step 3: Update `sebastian/config/README.md`**

Open the file, update the directory structure / properties table to reflect new layout. Add rows for `user_data_dir`、`logs_dir`、`run_dir`，移除 `sessions_dir` 行，把 `database_url` / `extensions_dir` / `workspace_dir` / `secret.key` 描述改为基于 `user_data_dir`。

例如表格新增条目示例：

```markdown
| `user_data_dir`（property） | — | `data_dir / "data"` | 用户数据子目录（db / secret / workspace / extensions） |
| `logs_dir`（property） | — | `data_dir / "logs"` | 日志目录 |
| `run_dir`（property） | — | `data_dir / "run"` | 运行时状态（pid、update 回滚备份） |
```

- [ ] **Step 4: Update root `README.md`**

如果有"目录结构"或"安装"小节，按以下要点更新：

1. 安装后的目录树示意改为新布局（参考 spec §2）
2. 新增"作为系统服务运行"小节：
   ```markdown
   ## 作为系统服务运行

   安装时若选择注册服务，或之后手动执行：

   ```bash
   sebastian service install   # 注册并启动
   sebastian service status    # 查看状态
   sebastian service stop      # 停止
   sebastian service uninstall # 卸载
   ```

   - macOS：`~/Library/LaunchAgents/com.sebastian.plist`
   - Linux：`~/.config/systemd/user/sebastian.service`（user-level，无需 sudo）

   Linux 用户如需开机自启，需手动开启 linger：
   `sudo loginctl enable-linger $USER`
   ```

- [ ] **Step 5: Update `CLAUDE.md`**

修改第 3 节"构建与启动"和第 6 节"运行时环境变量"：

1. 凡提到 `~/.sebastian/sebastian.db` / `~/.sebastian/secret.key` 的地方改为 `~/.sebastian/data/sebastian.db` / `~/.sebastian/data/secret.key`
2. 第 3 节末尾新增一段说明数据目录布局并指向 spec：
   ```markdown
   ### 数据目录布局（v2）

   ```
   ~/.sebastian/{app,data,logs,run}
   ```
   详见 `docs/superpowers/specs/2026-04-26-install-flow-overhaul-design.md`。
   ```

- [ ] **Step 6: Commit docs**

```bash
git add README.md sebastian/config/README.md CLAUDE.md
git commit -m "docs: 同步新布局到 README、config README、CLAUDE.md

- 根 README 新增'作为系统服务运行'小节
- config README 表格反映 user_data_dir/logs_dir/run_dir
- CLAUDE.md 路径示例改为 data/ 子目录

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: 端到端手动验证（PR 描述清单）

执行后记录在 PR description 的 Test plan 里：

- [ ] **Step 1: macOS 本地 dev 路径**

```bash
rm -rf ~/.sebastian-dev
./scripts/dev.sh
```

Expected：
- 终端打印新布局子目录提示
- 浏览器自动打开 setup 向导
- 完成向导后 `ls ~/.sebastian-dev/` 显示 `app/ data/ logs/ run/` 加 `.layout-v2`
- `~/.sebastian-dev/data/sebastian.db` 存在，根目录无 `sebastian.db`

- [ ] **Step 2: macOS 旧布局迁移路径**

```bash
# 备份现有目录后造一个 v1 假象
cp -r ~/.sebastian /tmp/sebastian-backup-$(date +%s)
rm ~/.sebastian/.layout-v2 2>/dev/null
mv ~/.sebastian/data/sebastian.db ~/.sebastian/sebastian.db 2>/dev/null
mv ~/.sebastian/data/secret.key ~/.sebastian/secret.key 2>/dev/null

sebastian serve
```

Expected: 启动日志含 `Detected v1 layout, migrating to v2...`，文件回到新位置，`.layout-v2` 重新生成。

- [ ] **Step 3: macOS service 安装**

```bash
sebastian service install
launchctl list | grep sebastian
sebastian service status
sebastian service uninstall
```

Expected: install 成功并能在 launchctl 看到 entry；status 显示 launchd 信息；uninstall 后 plist 文件被删除。

- [ ] **Step 4: Linux service（在 Docker 或 VM 内）**

```bash
sebastian service install
systemctl --user is-active sebastian.service
# 应该看到 active
sebastian service status
sebastian service uninstall
```

Expected: install 成功并触发 linger 检测提示；uninstall 后 unit 文件被删。

- [ ] **Step 5: install.sh 全流程**

```bash
SEBASTIAN_DATA_DIR=~/.sebastian-test ./scripts/install.sh
```

Expected: 走完 wizard、看到服务注册询问、装完直接退出而非长驻运行。

- [ ] **Step 6: bootstrap.sh 已有安装拦截**

```bash
SEBASTIAN_INSTALL_DIR=~/.sebastian/app bash bootstrap.sh
```

Expected: 报错并提示 `sebastian update`。

---

## Task 10: 创建 PR

- [ ] **Step 1: Push branch**

```bash
git push -u origin feat/install-flow-overhaul
```

- [ ] **Step 2: Create PR via gh**

```bash
gh pr create --base main --title "feat: 安装流程改造（数据布局 v2 + 系统服务）" --body "$(cat <<'EOF'
## Summary

- 重组 ~/.sebastian/ 为 {app,data,logs,run} 四级子目录，启动时自动迁移旧布局（.layout-v2 标记保证幂等）
- 新增 sebastian service install/uninstall/start/stop/status，支持 systemd user units (Linux) 和 launchd LaunchAgents (macOS)
- install.sh 装完即退，可选询问是否注册系统服务，不再阻塞为长期运行进程
- bootstrap.sh 检测已存在的 Sebastian 安装则拒绝覆盖，引导走 sebastian update

## Test plan

- [ ] macOS dev：./scripts/dev.sh 启动后 ~/.sebastian-dev/ 显示新布局
- [ ] macOS 迁移：从 v1 假象启动 sebastian serve 触发自动迁移
- [ ] macOS 服务：sebastian service install/status/uninstall 全流程
- [ ] Linux 服务：systemd user unit 安装 + linger 提示
- [ ] install.sh 全流程：wizard → 询问 → 退出
- [ ] bootstrap.sh：已有安装目录被拦截
- [ ] pytest tests/unit/test_layout_migration.py tests/unit/test_config_paths.py tests/unit/test_service_install.py tests/integration/test_updater_paths.py 全绿
- [ ] ruff check + ruff format --check + mypy 全绿

参考设计文档：docs/superpowers/specs/2026-04-26-install-flow-overhaul-design.md
EOF
)"
```

Expected: PR 创建成功，URL 打印。

---
