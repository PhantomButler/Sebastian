# Log 模块

> 上级：[sebastian/README.md](../README.md)

三层旋转文件日志系统，支持运行时热切换 LLM 流日志和 SSE 事件日志。

## 目录结构

```text
log/
├── __init__.py    # 全局 LogManager 单例（setup_logging / get_log_manager）
├── manager.py     # LogManager 类：三个 RotatingFileHandler 的生命周期管理
└── schema.py      # Pydantic 模型：LogState / LogConfigPatch
```

## 日志文件

所有日志写入 `${SEBASTIAN_DATA_DIR}/logs/`：

| 日志文件 | Logger 名称 | 默认状态 | 说明 |
|---------|-------------|---------|------|
| `main.log` | `sebastian` | 始终开启 | 全局 DEBUG 日志，所有子 logger 汇入 |
| `llm_stream.log` | `sebastian.llm.stream` | 默认关闭 | LLM 流式响应原始数据，`propagate=False` 不上冒 |
| `sse.log` | `sebastian.gateway.sse` | 默认关闭 | SSE 事件推送日志，`propagate=False` 不上冒 |

旋转策略：10 MB/文件，保留 3 个备份。

## 初始化

`setup_logging()` 在 Gateway lifespan 启动时调用一次：

```python
from sebastian.log import setup_logging
log_manager = setup_logging(data_dir=settings.data_dir)
```

之后通过 `get_log_manager()` 获取单例。

## 运行时热切换

通过 REST API `GET/PATCH /debug/logging` 控制 `llm_stream` 和 `sse` 的开关：

```python
log_manager.set_llm_stream(True)   # 挂载 handler 到 logger
log_manager.set_sse(False)         # 从 logger 移除 handler
state = log_manager.get_state()    # 返回 LogState
```

### Pydantic 模型

- `LogState`：完整状态（`llm_stream_enabled: bool`, `sse_enabled: bool`），用于 GET 响应
- `LogConfigPatch`：PATCH 请求体，字段均可选，仅传需要修改的

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 新增日志通道 | `manager.py`（新增 handler + toggle 方法） |
| 修改日志格式或旋转策略 | `manager.py`（`_FORMATTER` / `_MAX_BYTES` / `_BACKUP_COUNT`） |
| 修改 REST API 接口 | `gateway/routes/debug.py` + `schema.py` |
| 修改初始化时机 | `__init__.py` + `gateway/app.py` lifespan |

---

> 新增日志通道后，请同步更新本 README 与 `schema.py` 中的模型定义。
