# Context Compaction Module

> 上级：[Sebastian Backend](../README.md)

负责 **session 短期上下文的运行时压缩**：当长 session 接近模型上下文窗口时，把较旧的 timeline items 压缩为 `context_summary`，同时通过 `archived=true` 保留完整审计历史。

## 文件职责

| 文件 | 职责 |
|------|------|
| `usage.py` | `TokenUsage` dataclass 与 provider usage 归一化辅助 |
| `estimator.py` | `TokenEstimator` 本地兜底估算器（英文/中文/messages 结构） |
| `token_meter.py` | `ContextTokenMeter` 阈值判断（usage 0.70/0.85、estimate 0.65） |
| `compaction.py` | `SessionContextCompactionWorker` + `TurnEndCompactionScheduler` |
| `prompts.py` | context summary prompt（Markdown 7-section handoff） |

## 关键流程

1. **Provider usage 优先**：每次 `ProviderCallEnd` 携带 `TokenUsage`，由 `ContextTokenMeter` 判断是否超阈值。
2. **本地估算兜底**：缺失 usage 时调用 `TokenEstimator.estimate_messages_tokens()`。
3. **per-turn 模型窗口**：`TurnEndCompactionScheduler` 通过 `context_window_resolver(agent_type)` 调用 `LLMProviderRegistry.get_provider(agent_type).context_window_tokens` 动态解析阈值，不再硬编码 200k。
4. **后台异步压缩**：`TurnDone` 持久化后 `asyncio.create_task` 后台执行，不阻塞 stream。
5. **`context_compactor` 可绑定**：summary 生成走 `get_provider("context_compactor")`，无专属绑定时 fallback 到 `__default__`。

## 触发档与 reason

| 档位 | 阈值 | summary.payload.reason |
|------|------|------------------------|
| usage soft | input_tokens >= window * 0.70 | `auto_usage_threshold` |
| usage hard | input_tokens >= window * 0.85 | `auto_usage_hard` |
| estimate | estimated_tokens >= window * 0.65 | `auto_estimate_threshold` |
| 手动 | API `POST /sessions/{id}/compact` | `manual` |

## 范围选择

- `retain_recent_exchanges = 8`（最近 8 个用户交互保留原文）
- `min_compactable_items = 12`、`min_source_tokens = 8000`（dry_run 与 manual 豁免后者）
- exchange 优先用 `exchange_id/exchange_index`；旧数据按 `user_message` 边界回退
- 不完整 tool chain（缺 `tool_result`）跳过
- 已有 `context_summary` 不再二次压缩

## 修改导航

| 修改场景 | 入口 |
|----------|------|
| 调阈值或 retain 窗口 | `compaction.py` 顶部常量 |
| 改 summary prompt | `prompts.py` |
| 新增 provider usage 字段 | `usage.py` `TokenUsage` |
| 调本地估算精度 | `estimator.py` |
| API 改动 | `sebastian/gateway/routes/sessions.py` 的 `compact` / `compaction/status` |
| 原子 archive 流程 | `sebastian/store/session_timeline.py:compact_range` |

## 相关 Spec

- `docs/superpowers/specs/2026-04-24-context-compaction-design.md`
- `docs/superpowers/specs/2026-04-25-llm-catalog-account-model-binding-design.md` §上下文压缩接入
