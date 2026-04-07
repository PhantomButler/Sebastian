# config

> 上级索引：[sebastian/](../README.md)

## 模块职责

集中管理全局运行时配置。基于 `pydantic-settings` 将环境变量（`.env` 文件或系统环境）映射为强类型的 `Settings` 对象，并提供 `ensure_data_dir()` 初始化数据目录结构。全局单例 `settings` 在进程启动时创建，其他模块统一从此处 import，不直接读取 `os.environ`。

## 目录结构

```
config/
└── __init__.py    # Settings 类、全局单例 settings、ensure_data_dir()，导出公共 API
```

## 关键字段说明

| 字段 | 环境变量 | 默认值 | 说明 |
|------|---------|--------|------|
| `sebastian_owner_name` | `SEBASTIAN_OWNER_NAME` | `"Owner"` | 主人名字，用于系统 prompt |
| `data_dir`（property） | `SEBASTIAN_DATA_DIR` | `~/.sebastian` | 数据根目录，自动展开 `~` |
| `database_url`（property） | `SEBASTIAN_DB_URL` | 自动派生 | SQLite 连接串 |
| `sebastian_model` | `SEBASTIAN_MODEL` | `claude-opus-4-6` | 默认 LLM 模型 |
| `sebastian_sandbox_enabled` | `SEBASTIAN_SANDBOX_ENABLED` | `false` | 是否启用代码沙箱 |

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 新增配置字段 | [__init__.py](__init__.py) — 在 `Settings` 类添加字段 |
| 数据目录结构（sessions/extensions/workspace 等） | [__init__.py](__init__.py) — `ensure_data_dir()` 函数 |
| 修改 JWT 过期时间 / 算法 | [__init__.py](__init__.py) — `sebastian_jwt_*` 字段 |
| LLM 默认模型或 max tokens | [__init__.py](__init__.py) — `sebastian_model` / `llm_max_tokens` |

---

> 修改本目录或模块后，请同步更新此 README。
