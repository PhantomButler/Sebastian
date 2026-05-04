# config

> 上级索引：[sebastian/](../README.md)

## 模块职责

集中管理全局运行时配置。基于 `pydantic-settings` 将环境变量（`.env` 文件或系统环境）映射为强类型的 `Settings` 对象，并提供 `ensure_data_dir()` 初始化数据目录结构。全局单例 `settings` 在进程启动时创建，其他模块统一从此处 import，不直接读取 `os.environ`。

## 目录结构

```
config/
└── __init__.py    # Settings 类、全局单例 settings、ensure_data_dir()，导出公共 API
```

## 数据目录布局（v2）

```
~/.sebastian/
  app/         # 安装树（sebastian update 只动这里）
  data/        # 用户数据：sebastian.db / secret.key / workspace / extensions / browser
  logs/        # 日志
  run/         # PID + update 回滚备份
  .layout-v2   # 迁移标记
```

`data_dir`（`SEBASTIAN_DATA_DIR`）指向 `~/.sebastian/`，`user_data_dir` 是其 `data/` 子目录。旧版平铺布局会在 `sebastian serve` 启动时自动迁移。

## 关键字段说明

| 字段 | 环境变量 | 默认值 | 说明 |
|------|---------|--------|------|
| `sebastian_owner_name` | `SEBASTIAN_OWNER_NAME` | `"Owner"` | 主人名字，用于系统 prompt |
| `data_dir`（property） | `SEBASTIAN_DATA_DIR` | `~/.sebastian` | 数据根目录，自动展开 `~` |
| `user_data_dir`（property） | — | `<data_dir>/data` | 用户数据子目录（db/secret.key/workspace/extensions） |
| `logs_dir`（property） | — | `<data_dir>/logs` | 日志目录 |
| `run_dir`（property） | — | `<data_dir>/run` | PID 文件与 update 回滚备份目录 |
| `database_url`（property） | `SEBASTIAN_DB_URL` | 自动派生 | SQLite 连接串，路径为 `<user_data_dir>/sebastian.db` |
| `extensions_dir`（property） | — | `<user_data_dir>/extensions` | 动态工具扩展目录 |
| `workspace_dir`（property） | — | `<user_data_dir>/workspace` | 沙箱工作区目录 |
| `browser_dir`（property） | — | `<user_data_dir>/browser` | 浏览器运行数据根目录 |
| `browser_profile_dir`（property） | — | `<browser_dir>/profile` | Playwright 持久化 profile 目录 |
| `browser_downloads_dir`（property） | — | `<browser_dir>/downloads` | 浏览器下载文件目录 |
| `browser_screenshots_dir`（property） | — | `<browser_dir>/screenshots` | 浏览器截图输出目录 |
| `sebastian_secret_key_path` | `SEBASTIAN_SECRET_KEY_PATH` | `""` | 显式覆盖 secret.key 路径；空时使用 `<user_data_dir>/secret.key` |
| `sebastian_model` | `SEBASTIAN_MODEL` | `claude-opus-4-6` | 默认 LLM 模型 |
| `sebastian_sandbox_enabled` | `SEBASTIAN_SANDBOX_ENABLED` | `false` | 是否启用代码沙箱 |
| `sebastian_browser_headless` | `SEBASTIAN_BROWSER_HEADLESS` | `true` | 浏览器运行是否使用 headless 模式 |
| `sebastian_browser_viewport` | `SEBASTIAN_BROWSER_VIEWPORT` | `1280x900` | 浏览器默认 viewport 字符串 |
| `sebastian_browser_timeout_ms` | `SEBASTIAN_BROWSER_TIMEOUT_MS` | `30000` | 浏览器操作默认超时时间（毫秒） |
| `sebastian_browser_dns_mode` | `SEBASTIAN_BROWSER_DNS_MODE` | `auto` | 浏览器安全解析模式：`auto` / `system` / `doh` |
| `sebastian_browser_doh_endpoint` | `SEBASTIAN_BROWSER_DOH_ENDPOINT` | `https://dns.alidns.com/resolve` | `doh` 或代理 Fake-IP fallback 使用的 DoH endpoint |
| `sebastian_browser_doh_timeout_ms` | `SEBASTIAN_BROWSER_DOH_TIMEOUT_MS` | `5000` | 浏览器 DoH 查询超时时间（毫秒） |
| `sebastian_browser_upstream_proxy` | `SEBASTIAN_BROWSER_UPSTREAM_PROXY` | `""` | 可选浏览器上游 HTTP 代理；为空时直连公网目标 |

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 新增配置字段 | [__init__.py](__init__.py) — 在 `Settings` 类添加字段 |
| 数据目录结构（extensions/workspace/browser 等） | [__init__.py](__init__.py) — `ensure_data_dir()` 函数 |
| 修改 JWT 过期时间 / 算法 | [__init__.py](__init__.py) — `sebastian_jwt_*` 字段 |
| LLM 默认模型或 max tokens | [__init__.py](__init__.py) — `sebastian_model` / `llm_max_tokens` |

---

> 修改本目录或模块后，请同步更新此 README。
