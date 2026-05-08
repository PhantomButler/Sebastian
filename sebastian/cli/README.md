# CLI 模块

> 上级：[sebastian/README.md](../README.md)

Typer CLI 子命令与进程守护工具，提供 `sebastian` 命令行入口的核心实现。

## 目录结构

```text
cli/
├── __init__.py       # 包定义
├── daemon.py         # PID 文件管理与进程生命周期
├── init_wizard.py    # 无头初始化向导（sebastian init --headless）
├── path_setup.py     # 稳定 CLI shim 与 shell PATH 配置
├── service.py        # systemd/launchd 服务安装、状态、重启
├── service_templates.py # systemd unit / launchd plist 模板渲染
├── skills.py         # Skill registry 搜索、安装、更新、移除命令
└── updater.py        # 自升级逻辑（sebastian update）
```

## 模块说明

### `daemon.py`

进程守护工具集，管理 PID 文件的读写与进程存活检测。

| 函数 | 职责 |
|------|------|
| `pid_path(data_dir)` | 返回标准 PID 文件路径 `data_dir/sebastian.pid` |
| `write_pid(path)` | 写入当前进程 PID |
| `read_pid(path)` | 读取 PID，文件缺失或损坏返回 `None` |
| `is_running(pid)` | 通过 `os.kill(pid, 0)` 检测进程是否存活 |
| `stop_process(path)` | 发送 `SIGTERM` 终止进程并清理 PID 文件 |

### `init_wizard.py`

无头服务器初始化向导，供 `sebastian init --headless` 使用。

- `run_headless_wizard()`：纯逻辑层，接收 `owner_store` + `secret_key_path` + `answers` 字典，创建 owner 账号并生成 JWT secret key。可单元测试。
- `run_interactive_headless_cli()`：Typer 驱动的交互式 CLI 入口，收集用户名/密码后调用上述纯逻辑函数。

密码要求：至少 8 字符，需二次确认。

### `path_setup.py`

安装与升级后的 CLI 入口配置工具。它会创建
`~/.sebastian/bin/sebastian` shim，稳定转发到当前安装目录的
`.venv/bin/sebastian`，并按当前 shell 写入幂等的 PATH block。

环境变量 `SEBASTIAN_SKIP_PATH_SETUP=1` 仅跳过 shell rc 文件更新，不会跳过
shim 生成，确保服务和工具调用仍可使用稳定入口。

### `updater.py`

自升级逻辑，实现 `sebastian update` 命令的完整流程：

1. 解析安装目录（优先 `SEBASTIAN_INSTALL_DIR`，其次 `~/.sebastian/app`，最后从 `sebastian.__file__` 反推）
2. 从安装目录的 `pyproject.toml` 读取当前版本
3. 通过 GitHub releases/latest 302 重定向获取最新 tag（避免 API 限流）
4. 下载 `sebastian-backend-<tag>.tar.gz` + `SHA256SUMS`
5. 强制 SHA256 校验
6. 解压到 staging 目录，原子交换 `MANAGED_ENTRIES`（sebastian/、pyproject.toml、scripts/ 等）
7. `pip install -e .` 更新依赖
8. 失败自动回滚到备份，成功后清理旧备份
9. 刷新 `~/.sebastian/bin/sebastian` CLI shim
10. 若检测到 active systemd/launchd 服务，优先自动重启服务；其次重启 legacy PID daemon；否则打印精确的手动启动指引

关键常量：
- `MANAGED_ENTRIES`：更新时替换的顶层条目，`.venv`/`.env`/`secret.key` 等不会被触碰
- `BACKUP_KEEP = 1`：只保留最近 1 个备份

### `skills.py`

Skill package manager 的 CLI 外壳，负责调用 registry client 与 installer：

- `search_registry()`：用 `RegistryClient.search()` 查询 registry，返回 CLI 行数据。
- `inspect`：展示 registry 中 Skill 的 slug、name、version、security、download、sha256 等信息。
- `install` / `update` / `remove`：安装、更新、移除 package-managed Skill，并在非默认 registry、强制覆盖、允许 runtime name 变更、移除等高影响操作前要求显式确认。
- `list`：展示当前 runtime Skill extensions 目录下的 managed / unmanaged Skill。

## CLI 命令一览

| 命令 | 说明 | 入口 |
|------|------|------|
| `sebastian serve` | 启动 Gateway（检测 setup mode） | `main.py` |
| `sebastian stop` | 终止后台进程 | `daemon.stop_process()` |
| `sebastian status` | 查看运行状态（识别 service / daemon） | `main.py` |
| `sebastian init --headless` | 无头服务器初始化 | `init_wizard.run_interactive_headless_cli()` |
| `sebastian update` | 自升级到最新 release | `updater.run_update()` |
| `sebastian version` | 输出当前 Sebastian 版本 | `main.py` |
| `sebastian --version` | 输出当前 Sebastian 版本 | `main.py` |
| `sebastian skills search <query>` | 搜索 registry Skill | `skills.search()` |
| `sebastian skills inspect <slug>` | 查看 registry Skill 详情 | `skills.inspect()` |
| `sebastian skills install <slug>` | 安装 Skill package | `skills.install()` |
| `sebastian skills list` | 查看已安装 Skill | `skills.list_command()` |
| `sebastian skills update <slug>` | 更新已安装 Skill | `skills.update()` |
| `sebastian skills remove <slug>` | 移除 package-managed Skill | `skills.remove()` |
| `sebastian service restart` | 重启 systemd/launchd 服务 | `service.restart()` |
| `sebastian service status` | 查看 systemd/launchd 服务状态与日志提示 | `service.status()` |

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 修改 CLI 命令注册或参数 | `main.py`（Typer app 定义） |
| 修改 Skill package manager CLI | `skills.py` |
| 修改进程守护/PID 逻辑 | `daemon.py` |
| 修改无头初始化流程 | `init_wizard.py` |
| 修改 CLI shim 或 PATH 写入逻辑 | `path_setup.py` |
| 修改自升级逻辑 | `updater.py` |

---

> 修改 CLI 命令后，请同步更新本 README 与 `sebastian/README.md` 中的相关描述。
