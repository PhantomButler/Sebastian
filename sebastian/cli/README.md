# CLI 模块

> 上级：[sebastian/README.md](../README.md)

Typer CLI 子命令与进程守护工具，提供 `sebastian` 命令行入口的核心实现。

## 目录结构

```text
cli/
├── __init__.py       # 包定义
├── daemon.py         # PID 文件管理与进程生命周期
├── init_wizard.py    # 无头初始化向导（sebastian init --headless）
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

### `updater.py`

自升级逻辑，实现 `sebastian update` 命令的完整流程：

1. 解析安装目录（从 `sebastian.__file__` 反推）
2. 通过 GitHub releases/latest 302 重定向获取最新 tag（避免 API 限流）
3. 下载 `sebastian-backend-<tag>.tar.gz` + `SHA256SUMS`
4. 强制 SHA256 校验
5. 解压到 staging 目录，原子交换 `MANAGED_ENTRIES`（sebastian/、pyproject.toml、scripts/ 等）
6. `pip install -e .` 更新依赖
7. 失败自动回滚到备份，成功后清理旧备份
8. 若检测到后台进程在运行，自动重启

关键常量：
- `MANAGED_ENTRIES`：更新时替换的顶层条目，`.venv`/`.env`/`secret.key` 等不会被触碰
- `BACKUP_KEEP = 1`：只保留最近 1 个备份

## CLI 命令一览

| 命令 | 说明 | 入口 |
|------|------|------|
| `sebastian serve` | 启动 Gateway（检测 setup mode） | `main.py` |
| `sebastian stop` | 终止后台进程 | `daemon.stop_process()` |
| `sebastian init --headless` | 无头服务器初始化 | `init_wizard.run_interactive_headless_cli()` |
| `sebastian update` | 自升级到最新 release | `updater.run_update()` |

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 修改 CLI 命令注册或参数 | `main.py`（Typer app 定义） |
| 修改进程守护/PID 逻辑 | `daemon.py` |
| 修改无头初始化流程 | `init_wizard.py` |
| 修改自升级逻辑 | `updater.py` |

---

> 修改 CLI 命令后，请同步更新本 README 与 `sebastian/README.md` 中的相关描述。
