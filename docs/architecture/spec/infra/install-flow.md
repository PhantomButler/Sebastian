---
version: "1.0"
last_updated: 2026-04-27
status: implemented
---

# 安装流程重构（Install Flow Overhaul）

*← [Infra 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 背景与目标

Sebastian 定位是"长期后台运行的个人 AI 管家"，但早期安装流程把它当成一次性 CLI 工具：

- `~/.sebastian/` 一层混了 app 代码、用户数据、运行时状态（pid 文件）
- `install.sh` 末尾 `exec sebastian serve` 把首启向导和长期运行揉在一起，无法干净退出
- 没有系统服务集成（systemd / launchd），用户必须手动 `sebastian serve`
- `bootstrap.sh` 对已存在安装目录直接 tar 覆盖，残留文件不清理

本次改造目标：

1. **数据目录结构化**：app / data / logs / run 各司其职
2. **服务化**：`sebastian service install/uninstall/start/stop/status` 子命令，支持 user-level systemd 和 launchd
3. **install.sh 拆分**：装完即退，可选询问是否注册服务，不再阻塞
4. **bootstrap.sh 收紧**：目标非空时拒绝覆盖，引导走 `sebastian update`

非目标：

- 不引入新的 daemon 进程管理框架（继续用现有 `sebastian/cli/daemon.py`）
- 不改 `SEBASTIAN_DATA_DIR` 环境变量语义（仍指 root `~/.sebastian/`）
- 不替用户跑 sudo（systemd linger 检测后只提示，不执行）

---

## 2. 数据目录新布局（v2）

```
~/.sebastian/
  app/                  # release 解压物 + venv，sebastian update 只动这里
    .venv/
    sebastian/...
    pyproject.toml
  .env                  # 安装态运行配置，service definitions 固定读取此文件
  data/                 # 用户数据
    sebastian.db
    secret.key          # chmod 600
    workspace/
    extensions/
    memory/             # 记忆快照（派生产物，可重建）
  logs/                 # 日志
    sebastian.log
    service.out.log     # 服务模式 stdout
    service.err.log     # 服务模式 stderr
  run/                  # 运行时状态
    sebastian.pid
    update-backups/     # sebastian update 回滚专用
  .layout-v2            # 迁移完成标记，内容为 schema 版本号 "2\n"
```

说明：

- `sessions/` 已废弃（session 现存 db），迁移时直接清理
- `~/.sebastian/backups/`（旧版 update 回滚目录）迁移到 `run/update-backups/`，与"用户数据 backup"概念分开
- `SEBASTIAN_DATA_DIR` 仍指 root，语义不变

---

## 3. 配置 API（`sebastian/config/__init__.py`）

### 新增属性

```python
@property
def user_data_dir(self) -> Path:
    return self.data_dir / "data"

@property
def logs_dir(self) -> Path:
    return self.data_dir / "logs"

@property
def run_dir(self) -> Path:
    return self.data_dir / "run"
```

### 路径变更汇总

| 原属性 | 新值 / 改动 |
|--------|------------|
| `data_dir` | 保持不变，= root（`~/.sebastian/`） |
| `database_url` | `f"sqlite+aiosqlite:///{user_data_dir}/sebastian.db"` |
| `sessions_dir` | 删除（已废弃） |
| `extensions_dir` | `user_data_dir / "extensions"` |
| `workspace_dir` | `user_data_dir / "workspace"` |
| `resolved_secret_key_path()` | `user_data_dir / "secret.key"` |

`ensure_data_dir()` 改为创建 `user_data_dir/extensions/{skills,agents}`、`user_data_dir/workspace`、`logs_dir`、`run_dir`，删掉 `sessions/sebastian`。

---

## 4. 启动时自动迁移（`sebastian/store/migration.py`）

新增 `migrate_layout_v2(data_root: Path) -> None`，调用时机：

- `sebastian serve`：启动早期、`init_db()` **之前**（必须先于打开 db）
- `sebastian init` / `sebastian init --headless`：在初始化向导最开始调用
- 任何依赖 `settings.user_data_dir` 的 CLI 子命令首次访问前（推荐放进 `cli/__init__.py` 全局入口装饰器）

```python
def migrate_layout_v2(data_root: Path) -> None:
    marker = data_root / ".layout-v2"
    if marker.exists():
        return

    legacy_db = data_root / "sebastian.db"
    if not legacy_db.exists():
        # 全新安装，建空骨架
        _ensure_new_dirs(data_root)
        marker.write_text("2\n")
        return

    logger.info("Detected v1 layout, migrating to v2...")
    for name in ["sebastian.db", "secret.key", "workspace", "extensions"]:
        src = data_root / name
        if src.exists():
            shutil.move(str(src), str(data_root / "data" / name))

    pid_src = data_root / "sebastian.pid"
    if pid_src.exists():
        shutil.move(str(pid_src), str(data_root / "run" / "sebastian.pid"))

    legacy_backups = data_root / "backups"
    if legacy_backups.exists():
        shutil.move(str(legacy_backups), str(data_root / "run" / "update-backups"))

    sessions = data_root / "sessions"
    if sessions.exists():
        shutil.rmtree(sessions)

    marker.write_text("2\n")
    logger.info("Layout migration v2 complete")
```

保证：

- 同一文件系统内 `mv` 是原子的
- 函数失败抛异常，启动直接终止；标记文件只在最后写入，半迁移状态不会被误判完成
- 标记内容 `2\n`，未来升级直接读数字判断

---

## 5. 系统服务子命令（`sebastian/cli/service.py`）

挂在 `sebastian service` 下的五个子命令：

```
sebastian service install     # 写 unit/plist + 启用
sebastian service uninstall   # 停止 + 删除 unit/plist
sebastian service start       # 启动
sebastian service stop        # 停止
sebastian service status      # active/inactive + tail logs
```

### 平台分发

| 平台 | 目标文件 | 机制 |
|------|----------|------|
| Linux | `~/.config/systemd/user/sebastian.service` | user-level，无需 sudo |
| macOS | `~/Library/LaunchAgents/com.sebastian.plist` | launchctl |
| 其他 | 报错退出 `unsupported platform: <os>` | — |

### systemd unit 模板（Linux）

`{DATA_ROOT}` 为 `SEBASTIAN_DATA_DIR` 解析后的安装数据根目录，默认
`~/.sebastian`；`{INSTALL_BIN}` 为该安装树中的 `sebastian` 可执行文件。

```ini
[Unit]
Description=Sebastian personal AI butler
After=network-online.target

[Service]
Type=simple
ExecStart={INSTALL_BIN} serve
EnvironmentFile=-{DATA_ROOT}/.env
Restart=on-failure
RestartSec=5
StandardOutput=append:{DATA_ROOT}/logs/service.out.log
StandardError=append:{DATA_ROOT}/logs/service.err.log

[Install]
WantedBy=default.target
```

`install` 后调 `systemctl --user daemon-reload && systemctl --user enable --now sebastian.service`。

**Linger 检测**：`loginctl show-user $USER -P Linger`，未开则打印提示，不自动执行 sudo。

### launchd plist 模板（macOS）

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.sebastian</string>
  <key>ProgramArguments</key>
  <array>
    <string>{INSTALL_BIN}</string>
    <string>serve</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>SEBASTIAN_ENV_FILE</key><string>{DATA_ROOT}/.env</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key>
    <string>{DATA_ROOT}/logs/service.out.log</string>
  <key>StandardErrorPath</key>
    <string>{DATA_ROOT}/logs/service.err.log</string>
</dict>
</plist>
```

`install` 后调 `launchctl load -w ~/Library/LaunchAgents/com.sebastian.plist`。

安装器会在 `<DATA_ROOT>/.env` 缺失时创建该文件。systemd 和 launchd 的
service definitions 都加载这个精确文件；自定义 `SEBASTIAN_DATA_DIR` 的安装
也必须继续使用 `<DATA_ROOT>/.env`，不要依赖源码工作目录 `.env`。

### 边界处理

- `install` 时已存在同名 unit/plist：报错并提示先 `service uninstall`
- `status` 输出：服务状态 + `tail -n 20 service.err.log`

---

## 6. install.sh 重构

新流程：

```
1. OS / Python 3.12+ 检查（保持）
2. venv 创建 + 依赖安装（保持）
3. sebastian init
   - 已初始化（user_data_dir/sebastian.db 存在）则跳过
   - 未初始化：有 $DISPLAY 或 macOS → web wizard；否则 → --headless
4. 询问："是否注册为开机自启服务？[y/N]" 默认 N
   - y → sebastian service install + sebastian service start
   - n → 打印提示
5. 打印下一步指引并退出（不再 exec sebastian serve）
```

关键：去掉末尾 `exec sebastian serve`。

### dev.sh 同步

`dev.sh` 主体不变（仍 `exec sebastian serve --reload`），只需更新首次初始化提示文案，说明新布局：

```
→  首次使用开发数据目录: ~/.sebastian-dev
   数据将分布在 ~/.sebastian-dev/{app,data,logs,run} 子目录
```

不需要在 `dev.sh` 内显式调 `sebastian init`——`sebastian serve` 检测到无 db 会自动唤起 wizard。

---

## 7. bootstrap.sh 收紧

解压前增加目标检测，已有安装时拒绝覆盖并引导升级：

```bash
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
```

---

## 8. 全局一致性修复

### daemon pid 路径（`sebastian/cli/daemon.py`）

`pid_path()` 形参从 `data_dir` 重命名为 `run_dir`，调用方全部传 `settings.run_dir`。

### updater 回滚目录（`sebastian/cli/updater.py`）

```python
def _backup_parent() -> Path:
    d = settings.run_dir / "update-backups"
    d.mkdir(parents=True, exist_ok=True)
    return d
```

updater 重启 daemon 时，`pid_path()` 也传 `settings.run_dir`（原 `settings.data_dir`）。

---

## 9. 测试

### 单元测试

- `tests/unit/test_layout_migration.py`
  - v1 → v2：构造旧布局，断言新位置正确、`sessions/` 删除、`backups/` → `run/update-backups/`、`.layout-v2` 存在
  - 已迁移：标记存在时不动文件
  - 全新安装（无 `sebastian.db`）：建空骨架 + 标记
- `tests/unit/test_config_paths.py`
  - `user_data_dir / logs_dir / run_dir` 路径正确
  - `database_url`、`extensions_dir`、`workspace_dir`、`resolved_secret_key_path` 全部落在 `data/` 子目录
- `tests/unit/test_service_install.py`
  - 渲染 systemd unit 模板（patch `sys.platform = "linux"`）
  - 渲染 launchd plist 模板（patch `sys.platform = "darwin"`）
  - mock `subprocess.run` 验证 systemctl/launchctl 调用参数
  - install 时目标文件已存在 → raise，提示 uninstall

### 集成测试

- `tests/integration/test_updater_paths.py`：`_backup_parent()` 落到 `run_dir / "update-backups"`，rollback 路径正确

---

## 10. 风险与回滚

- **迁移失败**：抛异常终止启动，文件留在原位；设计上不做半回滚，定位问题更直接
- **服务模板平台差异**：systemd 路径用 `%h` 占位符，launchd 路径用真实 HOME 渲染（plist 不支持环境变量替换）
- **现有 daemon 在跑**：迁移在 daemon 启动早期、读 pid 之前完成；从 systemd/launchd 拉起的服务，service install 后第一次启动时触发迁移，正常

---

*← [Infra 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
