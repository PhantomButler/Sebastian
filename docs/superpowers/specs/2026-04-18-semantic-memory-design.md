---
version: "1.1"
last_updated: 2026-04-18
status: ready-for-impl
---

# SemanticMemory 系统设计

*← [Spec 根索引](../../../docs/architecture/spec/INDEX.md)*
*架构图：[docs/architecture/diagrams/memory-v0.3.html](../../architecture/diagrams/memory-v0.3.html)*

---

## 1. 背景与动机

Sebastian 当前记忆体系只有两层：

| 层 | 实现 | 问题 |
|----|------|------|
| WorkingMemory | 进程内 task KV | 重启即丢，Agent 未主动使用 |
| EpisodicMemory | `~/.sebastian/sessions/{agent_type}/{session_id}/messages.jsonl` | 仅限当前 session 最近 20 条，跨 session 完全失忆 |

> **重要**：Session 存储是**纯文件系统**实现（`SessionStore`），不涉及 SQLite。每条消息追加写入 `messages.jsonl`，`get_messages()` 读最后 limit 行。当前情景记忆的实质是"本次对话的上下文缓冲区"，不是可检索的记忆。

**核心痛点**：Agent 每次新对话从零开始，用户要反复说明偏好、背景；越用越陌生，而非越用越懂用户。

**目标**：让 Sebastian 像贾维斯一样越用越懂用户，跨 session 记住用户偏好、项目背景、重要事实，逐渐磨合配合默契。

---

## 2. 非目标（本期不做）

- Sub-Agent 独立记忆（ForgeAgent 等读写自己的记忆）——后续按需扩展，基础设施已预留 hook
- 跨 session 情景检索（"找上个月那次调试的对话"）——需要对 messages.jsonl 建全文索引，复杂度更高，单独立项
- 情景记忆压缩（长对话 20 条截断问题）——与本期正交，单独立项
- 多用户隔离记忆——当前 Sebastian 单 Owner，暂不需要

---

## 3. 架构概览：三层记忆

```
WorkingMemory    → 进程内临时 KV，task 作用域，重启丢失（已有，未主动用）
EpisodicMemory   → 文件系统对话历史，session 作用域，本次对话缓冲（已有）
SemanticMemory   → SQLite 长期语义记忆，Owner 全局，跨 session 持久（本期新建）
```

SemanticMemory 存储在现有 SQLite DB（`~/.sebastian/sebastian.db`），**不引入新基础设施依赖**。

---

## 4. 数据模型

### 4.1 memories 表

```sql
CREATE TABLE memories (
    id                TEXT PRIMARY KEY,        -- UUID
    category          TEXT NOT NULL,           -- preference | fact | project | habit | constraint
    entity_key        TEXT,                    -- FK → memory_keys.key；NULL 表示自由文本记忆
    entity_value      TEXT,                    -- 结构化值，与 entity_key 配对
    content           TEXT NOT NULL,           -- 自然语言描述，供展示/注入 system prompt
    content_segmented TEXT NOT NULL,           -- jieba 预分词结果（空格连接），供 FTS5 检索
    source            TEXT NOT NULL,           -- explicit（用户主动）| inferred（Agent 推断）
    confidence        REAL DEFAULT 1.0,        -- 0.0–1.0；explicit 固定 1.0
    expires_at        DATETIME,                -- NULL 永久有效；临时偏好设 TTL
    source_session_id TEXT,                    -- 来源 session，追溯用
    created_at        DATETIME NOT NULL,
    updated_at        DATETIME NOT NULL,
    last_accessed_at  DATETIME,               -- 被注入的最近时间
    access_count      INTEGER DEFAULT 0        -- 被注入次数，排序权重
);

-- FTS5 全文索引（外部内容表，索引 content_segmented，Python 层写入时同步）
CREATE VIRTUAL TABLE memories_fts USING fts5(
    content_segmented,
    content='memories',
    content_rowid='rowid',
    tokenize='unicode61'   -- 默认 Unicode 分词，配合 jieba 预分词空格切割
);
```

**写入时**：Python 调用 `' '.join(jieba.cut(content))` 生成 `content_segmented`，两列同步写入。  
**查询时**：对用户消息同样用 jieba 分词，取每个词（`len > 1`）分别做 FTS5 MATCH，结果合并去重。

### 4.2 memory_keys 表（entity_key 动态注册）

```sql
CREATE TABLE memory_keys (
    key          TEXT PRIMARY KEY,   -- 如 communication_style
    description  TEXT NOT NULL,      -- 给 LLM 的说明，用于提取 prompt
    category     TEXT,               -- 归属分类
    example      TEXT,               -- 示例值，辅助 LLM 判断
    is_builtin   BOOLEAN DEFAULT FALSE,  -- True = 迁移 seed；False = 运行时发现
    usage_count  INTEGER DEFAULT 0,  -- 引用此 key 的 memory 数，供 API 展示
    created_at   DATETIME NOT NULL
);
```

**内建 key 约 25 个**，在 `_apply_idempotent_migrations()` 中 seed，包含：
`communication_style` / `current_project` / `work_schedule` / `timezone` /
`dietary_preference` / `wake_time` / `tech_stack` / `coding_style` 等。

### 4.3 Upsert 冲突策略

- 有 `entity_key` → 按 key 查找已有记录 → 新值 `confidence > 旧值 × 0.8` 则覆盖；`explicit` 永远覆盖 `inferred`
- `entity_key=NULL` → 直接 INSERT；Insert 前做 content 精确去重（`WHERE content = ?`）

---

## 5. entity_key 混合策略

**三分支判断**（LLM 提取时决定）：

```
事实提取结果
  ├─ 匹配已有 memory_key → 有 entity_key，走 Upsert（去重保证）
  ├─ 新的结构化概念（值得长期追踪）→ is_new_key=True，写入 memory_keys，再走 Upsert
  └─ 一次性零散事实 → entity_key=NULL，走 Insert（content 精确去重兜底）
```

**LLM 提取返回 JSON 格式**：
```json
[
  {
    "entity_key": "communication_style",
    "entity_value": "简洁中文",
    "content": "用户偏好简洁的中文回复",
    "confidence": 0.95,
    "is_new_key": false
  },
  {
    "entity_key": "pet_name",
    "entity_value": "小橘",
    "content": "用户的猫叫小橘",
    "confidence": 0.9,
    "is_new_key": true,
    "key_description": "宠物名字",
    "key_category": "fact"
  },
  {
    "entity_key": null,
    "content": "用户本周四有重要会议",
    "confidence": 0.8,
    "expires_in_days": 7
  }
]
```

**自扩展机制**：ConsolidationWorker 每次运行都从 DB 读取完整 key 列表传给 LLM，新 key 写回后下次自动包含，key 库随使用不断丰富。

---

## 6. 写入流水线

### 路径 A：即时写入（用户主动）

```
用户说"记一下..." → Agent 调用 memory_save 工具
→ 查 memory_keys 匹配 entity_key（无匹配则 NULL）
→ Upsert or Insert（source=explicit, confidence=1.0）
→ 同步更新 FTS5 索引
```

### 路径 B：Session 沉淀（后台异步）

```
Session 状态 → idle 或 stalled
→ EventBus 发布 SESSION_IDLE
→ ConsolidationWorker 异步触发
→ 检查 session.consolidated 标记，避免重复处理
→ 构建 LLM prompt：
    ① SELECT key, description FROM memory_keys（known_keys 上下文）
    ② SELECT content FROM memories WHERE entity_key IS NULL
       AND created_at > now-30days LIMIT 20（近期 NULL 记忆，语义去重用）
    ③ 读取 session 完整对话历史
→ 调用 LLM（绑定 memory_consolidation provider）提取 JSON
→ 逐条处理：新 key 写 memory_keys → Upsert or Insert memories
→ session.consolidated = True
```

**不做每 turn 提取**：噪音大且额外消耗 LLM API，只在 session 自然结束后整体提取一次。

---

## 7. 读取流水线

### 7.1 被动注入（每次 turn 自动，双层）

在 `_stream_inner()` 开始时，仿 `_session_todos_section()` 模式：

**Profile 层（top-4，不用 FTS5）**
```sql
SELECT content, entity_key, entity_value FROM memories
WHERE expires_at IS NULL OR expires_at > datetime('now')
ORDER BY access_count DESC
LIMIT 4
```
高频访问 = 对所有对话都相关的基础事实（沟通风格、当前项目等）。

**Context 层（top-4，FTS5 MATCH 当前用户消息）**

Python 层先对用户消息做 jieba 分词，取有效词（`len > 1`）逐词查询：

```python
terms = [t for t in jieba.cut(user_message) if len(t) > 1]
# 逐词 MATCH，合并去重，排除 profile 层已选 ID
```

```sql
SELECT m.content, m.id FROM memories m
JOIN memories_fts f ON m.rowid = f.rowid
WHERE f.memories_fts MATCH :term      -- 传入单个 jieba 分词结果
  AND (m.expires_at IS NULL OR m.expires_at > datetime('now'))
  AND m.id NOT IN (<profile层已选ID>)
ORDER BY f.rank
LIMIT 4
```

多个词的结果在 Python 层合并去重，按 FTS5 rank 重排后取 top-4。

**合并去重后注入 system prompt**，最多 8 条，格式：
```
## What I know about you
- 你偏好简洁中文回复
- 当前项目：Sebastian AI 管家
...
```

**同时更新** `access_count +1` 和 `last_accessed_at`。

### 7.2 主动查询（memory_search 工具）

Agent 调用 `memory_search(query)` → FTS5 MATCH query → 加权排序返回列表。

---

## 8. 与 Agent Loop 集成（4 个 Hook）

| Hook | 位置 | 改动 |
|------|------|------|
| 1 被动注入 | `core/base_agent.py _stream_inner()` | 加 `_memory_section()`，双层查询拼入 prompt |
| 2 即时写入 | `capabilities/tools/memory_save.py` | 新增 @tool，LOW 权限 |
| 3 主动查询 | `capabilities/tools/memory_search.py` | 新增 @tool，FTS5 检索 |
| 4 Session 沉淀 | `memory/consolidation.py` | ConsolidationWorker，订阅 SESSION_IDLE/STALLED |

**最小侵入原则**：不改 AgentLoop 核心逻辑，全部在 BaseAgent 层和工具层处理。

---

## 9. FTS5 Tokenizer — 决策：jieba 预分词 + unicode61

实测环境（SQLite 3.51.0 / Python 3.12）：

| 方案 | 实测结果 | 结论 |
|------|----------|------|
| **trigram**（SQLite 3.34+ 内置）| 可用，但**2 字中文词无法命中**（`中文`/`项目`/`偏好` 均匹配失败，最少需 3 字才能构成 trigram） | ❌ 淘汰：2 字词是中文最常见词型 |
| **ICU tokenizer** | `no such tokenizer: icu` — Python 标准 sqlite3 未编译此扩展 | ❌ 淘汰：部署不可控 |
| **jieba 预分词 + unicode61** | 完全可用，2 字词精确命中，中英混合良好，查询召回率高 | ✅ **选定** |

### 实现方案

```
写入：content → jieba.cut() → ' '.join() → content_segmented 列
检索：user_message → jieba.cut() → 取 len>1 的词 → 逐词 FTS5 MATCH → 合并去重
```

**依赖**：`jieba>=0.42`（已加入 `pyproject.toml [memory]` extra）

### 为什么不用 trigram

2 字中文词（用户、项目、偏好、中文、简洁、管家……）是最高频的语义单元，trigram 全部漏掉，上下文层的 FTS5 检索会大面积失效，不可接受。

### unicode61 的角色

jieba 已经完成分词，`content_segmented` 里每个词之间有空格。`unicode61` 只需按空白边界切 token，不需要复杂的语言感知——等于只做"空白分割"，职责恰当。

---

## 10. 功能开关

`Settings` 新增 `memory_enabled: bool`（默认 `True`），通过 `SEBASTIAN_MEMORY_ENABLED` 环境变量控制。

关闭时：
- `_memory_section()` 返回空字符串
- `memory_save` / `memory_search` 返回"记忆功能已关闭"
- `ConsolidationWorker` 跳过处理
- 数据保留在 DB，重新开启即恢复

---

## 11. LLM Provider 绑定

沿用现有 `agent_llm_bindings` 机制（`LLMProviderRegistry.get_provider(name)`），新增两个可绑定名称：

| 名称 | 用途 | 建议 |
|------|------|------|
| `permission_reviewer` | MODEL_DECIDES 工具审批 | 快速低延迟模型 |
| `memory_consolidation` | Session 沉淀提取 | 便宜小模型，不在主路径 |

Android App Settings 的 LLM Provider Bindings 列表新增 **System Components** 分区展示两者，复用现有绑定 UI 组件。

---

## 12. 新增工具

| 工具 | 权限 | 说明 | 适用 Agent |
|------|------|------|-----------|
| `memory_save` | LOW | 即时写入，source=explicit | 所有 Agent |
| `memory_search` | LOW | FTS5 检索返回列表 | 所有 Agent |
| `memory_list` | LOW | 列出记忆供用户核查 | 仅 Sebastian |
| `memory_delete` | LOW | 删除记忆，同步更新 FTS5 | 仅 Sebastian |

新增 REST API：`GET /api/v1/memory/keys` — 返回 memory_keys 表，供 Android 展示当前 key 库。

---

## 13. 新增文件清单

```
sebastian/memory/
├── semantic_memory.py        ← SemanticMemory 类（查询、Upsert、被动注入）
└── consolidation.py          ← ConsolidationWorker（订阅事件、LLM 提取、写入）

capabilities/tools/
├── memory_save.py            ← @tool memory_save
├── memory_search.py          ← @tool memory_search
├── memory_list.py            ← @tool memory_list（Sebastian only）
└── memory_delete.py          ← @tool memory_delete（Sebastian only）

store/
└── migrations 中新增 memories / memory_keys 建表 + seed builtin keys
```

**修改文件**：
- `core/base_agent.py`：`_stream_inner()` 加 `_memory_section()`
- `config.py`：加 `memory_enabled` 字段
- `gateway/app.py`：lifespan 启动 ConsolidationWorker
- `protocol/events/types.py`：确认 SESSION_IDLE / SESSION_STALLED 事件已有

---

## 14. 开放问题

| 问题 | 状态 |
|------|------|
| FTS5 中文 tokenizer 选型 | ✅ 已决策：jieba 预分词 + unicode61（见 §9） |
| 被动注入 top-N 数量是否需要可配置 | 待定，先硬编码 8 |
| memory_consolidation LLM 提取 prompt 具体设计 | 实现时确定 |
| NULL 记忆长期积累的清理策略（30天无访问自动归档？） | 留待迭代 |

---

*← 返回 [Spec 根索引](../../../docs/architecture/spec/INDEX.md)*
