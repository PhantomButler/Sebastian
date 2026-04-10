---
version: "1.0"
last_updated: 2026-04-10
status: implemented
---

# 日志追踪系统设计

*← [Core 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 背景与目标

- 将所有日志持久化写入文件，支持自动轮转
- 将高频流式 delta 日志隔离到独立文件，避免污染主日志
- 支持 App 端运行时热切换，无需重启后端

---

## 2. 日志文件设计

日志目录：`$SEBASTIAN_DATA_DIR/logs/`

| 文件 | Logger 名称 | 默认级别 | 默认状态 | 内容 |
|------|------------|---------|---------|------|
| `main.log` | `sebastian`（root） | INFO | 始终开启 | 所有模块常规日志 |
| `llm_stream.log` | `sebastian.llm.stream` | DEBUG | 关闭 | LLM token delta + stream events |
| `sse.log` | `sebastian.gateway.sse` | DEBUG | 关闭 | SSE EventBus 广播 payload |

**轮转策略**（三个文件统一）：
- 单文件上限：10 MB（`maxBytes=10_485_760`）
- 最多保留 3 份备份（`backupCount=3`）
- 备份命名：`main.log.1`、`main.log.2`、`main.log.3`

**日志格式**：
```
2026-04-04 15:23:01.123 | INFO     | sebastian.orchestrator.conversation | [session:abc123] Turn started
```

格式字符串：`%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)s | %(message)s`

---

## 3. 后端模块

```
sebastian/log/
├── __init__.py      # 暴露 LogManager 单例、setup_logging()、get_log_manager()
├── manager.py       # LogManager：handler 生命周期管理、热切换
└── schema.py        # LogState / LogConfigPatch pydantic 模型
```

### 3.1 数据模型

```python
class LogState(BaseModel):
    llm_stream_enabled: bool
    sse_enabled: bool

class LogConfigPatch(BaseModel):
    llm_stream_enabled: bool | None = None
    sse_enabled: bool | None = None
```

### 3.2 LogManager

单例，在 Gateway lifespan 启动时由 `setup_logging()` 初始化。

**初始化流程**：
1. 确保 `$DATA_DIR/logs/` 目录存在
2. 为 `sebastian` root logger 挂载 `RotatingFileHandler` → `main.log`，同时保留 console handler
3. 创建 `sebastian.llm.stream` / `sebastian.gateway.sse` 专属 logger，设 `propagate=False`
4. 预创建两个 `RotatingFileHandler` 但不挂载，等 toggle 调用时才 add
5. 从环境变量读取初始开关状态

**热切换**：

```python
def set_llm_stream(self, enabled: bool) -> None:
    logger = logging.getLogger("sebastian.llm.stream")
    if enabled:
        logger.addHandler(self._llm_stream_handler)
    else:
        logger.removeHandler(self._llm_stream_handler)
    self._state.llm_stream_enabled = enabled

def set_sse(self, enabled: bool) -> None:
    # 同上

def get_state(self) -> LogState:
    return LogState(...)
```

`addHandler` / `removeHandler` 内部持有 `logging._acquireLock()`，线程安全。

### 3.3 现有代码改动

- **无需改动现有 `logger.xxx()` 调用**
- 流式 delta 使用专属 logger：
  - `logging.getLogger("sebastian.llm.stream")` 记 LLM delta
  - `logging.getLogger("sebastian.gateway.sse")` 记 SSE payload

---

## 4. 配置项

```python
# sebastian/config/__init__.py
sebastian_log_llm_stream: bool = False
sebastian_log_sse: bool = False
```

环境变量：`SEBASTIAN_LOG_LLM_STREAM`、`SEBASTIAN_LOG_SSE`

---

## 5. API 接口

路由文件：`sebastian/gateway/routes/debug.py`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/debug/logging` | 返回当前两个开关状态 |
| PATCH | `/api/debug/logging` | 部分更新开关，即时生效 |

需要 JWT 认证。

**GET 响应**：
```json
{ "llm_stream_enabled": false, "sse_enabled": false }
```

**PATCH 请求**：
```json
{ "sse_enabled": true }
```

**PATCH 响应**：更新后的完整 `LogState`。

---

## 6. App Settings UI

在 Settings 页面"调试日志"分组：

```
─── 调试日志 ──────────────────────
  LLM Stream 日志       [  ○  ]
  SSE 事件日志          [  ○  ]
───────────────────────────────────
```

- 进入 Settings 页时 GET 回填初始状态
- 拨动开关立即 PATCH，无需确认
- 请求失败时 toast + 回滚开关

---

## 7. 数据流

```
App toggle → PATCH /api/debug/logging
           → LogManager.set_llm_stream(true)
           → logger.addHandler(llm_stream_handler)
           → 后续 agent_loop 中 getLogger("sebastian.llm.stream").debug(...)
           → 写入 $DATA_DIR/logs/llm_stream.log（10MB 轮转 × 3 备份）
```

---

## 8. 不在本 spec 范围内

- 日志查看 API（从 App 读取日志内容）
- 日志级别细粒度控制
- 结构化 JSON 日志格式
- 远程日志聚合

---

*← [Core 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
