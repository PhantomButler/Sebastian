---
integrated_to: memory/retrieval.md
integrated_at: 2026-04-21
---

# Memory Retrieval Path Fixes — Design Spec

**Date**: 2026-04-20
**Status**: Draft — pending user review
**Scope**: `sebastian/memory/` 记忆模块读路径（retrieval / injection）
**Related**: `docs/architecture/spec/memory/retrieval.md` §3/§4/§7、`docs/architecture/spec/memory/artifact-model.md` §9.3/§10.4、`sebastian/memory/data-flow.md`

---

## 1. Goals

修复 Memory 自动注入链路上三处与架构 Spec 不一致的实现：

1. **B1 — depth 注入控制**：`_memory_section()` 只在 `depth == 1` 的 Sebastian 本体注入长期记忆，`depth >= 2` 的子 agent 与 `depth` 未初始化的入口一律 fail-closed 返回空（对应 artifact-model.md §10.4）
2. **B2 — confidence 双阈值**：把当前的单阈值 `MIN_CONFIDENCE = 0.3` 拆成两级——`0.3` 硬过滤线（所有路径共用），`0.5` 自动注入门槛（仅 `context_injection` 路径），让 `tool_search` 能返回低置信弱线索而自动注入保持高质量（对应 retrieval.md §7.3 / artifact-model.md §9.3）
3. **B3 — Planner 词库与分词升级**：把关键词列表 + substring 匹配升级为 `frozenset` + `jieba.lcut()` 精确分词；新增 `retrieval_lexicon.py` 独立文件托管词库；relation lane 触发词在启动时与 Entity Registry 合并，并在 Entity Registry 写入路径末尾显式 reload 缓存（对应 retrieval.md §3 / §4.4）

同时完成配套动作：

4. **清理** `sebastian/memory/prompts.py` / Spec A 文档里诱导 LLM 设 `pinned` 的字样
5. **明确声明** `pinned` 豁免 budget（原 B4）不在本 spec，并在 `docs/architecture/spec/memory/retrieval.md §7.4` 更新"实现状态"

## 2. Non-Goals

- **`pinned` 豁免 budget 的实现**：Spec §7.4 / §10.1 / §10.3 定义完整，但本 spec 明确不实现（详见 §13）
- **写路径 / Extractor / Consolidator / Resolver**：本 spec 只碰读路径；唯一的写路径触点是 Entity Registry 写入末尾加一行 `planner.reload_entity_triggers()`，属于读缓存同步，不是写逻辑变更
- **引入 LLM 做意图判断**：读路径是同步阻塞，每轮 +200ms 首 token 延迟不可接受
- **引入 embedding / 向量库**：`memory/INDEX.md` 明确"首版只依赖 DB + LLM"
- **per-purpose 可配置 min_confidence（如 `memory_search(min_confidence=0.1)`）**：本 spec 仅处理 `context_injection` / `tool_search` 两档固定阈值；更低阈值的工具参数留给未来
- **event bus 驱动的 Entity 变更同步**：本 spec 用直接调用（`planner.reload_entity_triggers()`），不引入发布-订阅

---

## 3. 现状与问题

### 3.1 B1 — depth 未被检查，子 agent 泄露主人记忆

- `sebastian/core/base_agent.py:236` `_memory_section()` 对所有 depth 的 agent 执行同样逻辑
- `sebastian/core/base_agent.py:555` `depth=getattr(self, "_current_depth", {}).get(session_id, 1)` 默认值为 `1`，fail-open
- 后果：组长 / 组员 agent 的 system prompt 里同样出现"用户偏好 / 画像 / relation"等本该只给 Sebastian 本体的长期记忆

### 3.2 B2 — 单阈值导致弱推断被无差别注入

- `sebastian/memory/retrieval.py:21` 仅 `MIN_CONFIDENCE = 0.3`
- `_keep_record()` 和 `MemorySectionAssembler._keep` 都用同一个阈值过滤
- 后果：`context_injection` 路径会拿到 confidence ∈ [0.3, 0.5) 的弱推断记忆，agent 把它当"事实"使用；`tool_search` 反而受同一阈值约束，用户显式查询也拿不到中间带候选

### 3.3 B3 — 关键词 substring + 私有实体盲区

- 四个 `list[str]` 常量（`PROFILE_LANE_KEYWORDS` / `CONTEXT_LANE_KEYWORDS` / `EPISODE_LANE_KEYWORDS` / `RELATION_LANE_KEYWORDS`）
- 匹配方式 `any(k in user_message.lower() for k in KEYWORDS)` 是 O(n_message × n_keywords) 的 substring 包含
- 后果 1：语义污染——"我需要一封推荐信" 会误激活 Profile Lane（substring `推荐` 命中）
- 后果 2：用户私有实体（家人名 / 项目名 / 宠物名）**永远不可能命中 relation lane**——词库不可能写死所有用户的私有命名空间
- 后果 3：同义词覆盖差（"妻子" / "爱人" / "太太" 都不在 `["老婆"]` 里）

### 3.4 Pinned 字样在 LLM prompt 里诱导错用

- `sebastian/memory/prompts.py:152` Extractor 字段表写了 `policy_tags | array<string> | 一般 []；"pinned" 表示钉住`
- 但 Spec §10.2 规定 LLM Extractor **不可**提议 `pinned`
- 后果：LLM 可能把"感觉重要"的记忆标 `pinned`，违反 Spec，且当前代码无任何防护

---

## 4. 术语

| 术语 | 含义 |
|---|---|
| **lane** | 记忆读路径的四条通道：Profile / Context / Episode / Relation |
| **Planner 层** | `MemoryRetrievalPlanner.plan()`，决定**哪些 lane 激活**、每条 lane 的 budget |
| **Store 层** | 各 lane 对应的查询方法（如 `profile_store.search_active`），决定**命中哪些记录** |
| **context_injection** | 自动注入路径（`_memory_section()` → system prompt） |
| **tool_search** | 用户显式工具调用路径（`memory_search(query)`） |
| **depth** | Agent 在当前会话中的层级；Sebastian 本体 = 1，被调度的子 agent = 2+ |
| **硬过滤线（hard gate）** | 任何路径都丢的 confidence 最低值 |
| **自动注入门槛（auto-inject gate）** | 仅 `context_injection` 路径额外应用的门槛 |

---

## 5. B1 — depth 注入控制

### 5.1 规则

- `depth == 1` → 注入
- `depth >= 2` → 不注入（组长、组员）
- `depth is None`（未在 `_current_depth` 中） → 不注入（**fail-closed**）
- `depth == 0` → 不注入（理论上不会出现，作为防御）

### 5.2 实现位置

**唯一触点**：`sebastian/core/base_agent.py` 的 `_memory_section()` 方法顶部守卫。

```python
# sebastian/core/base_agent.py
async def _memory_section(
    self,
    session_id: str,
    agent_context: AgentContext,
    user_message: str,
) -> str:
    depth = self._current_depth.get(session_id)
    if depth != 1:
        return ""
    # ... 原有逻辑不变
```

### 5.3 Scope 边界：不改 `ToolCallContext.depth` 默认值

`base_agent.py:555` 存在类似的 fail-open 隐患：

```python
depth=getattr(self, "_current_depth", {}).get(session_id, 1),  # 传给 ToolCallContext
```

但这是**工具调用上下文**的 depth 字段传递，与记忆注入守卫**不同路径、不同决策域**。本 spec **不处理**这一行——scope 严格限定在记忆注入读路径。如果该处需要同样的 fail-closed 改造，应单独开 spec 评估（涉及工具调用权限模型，不宜在 Retrieval Fixes 里隐式带进）。

### 5.4 设计理由

- **Spec §10.4** 原文："长期记忆注入只对 depth=1 的 Sebastian 本体开放"
- fail-closed 强制所有新入口（测试、新 agent 类型）显式赋值 depth，消除"忘赋值导致子 agent 误拿主人记忆"的泄露通道
- 守卫放在 `_memory_section()` 内部（而非调用侧或 agent 注册层），因为该方法是所有 agent 共享的唯一注入入口，内聚性最高

---

## 6. B2 — confidence 双阈值

### 6.1 阈值定义

替换 `sebastian/memory/retrieval.py` 的 `MIN_CONFIDENCE`：

```python
# 删除旧常量
# MIN_CONFIDENCE = 0.3

# 新增两个常量
MIN_CONFIDENCE_HARD: float = 0.3          # 绝对硬过滤线，任何路径都丢
MIN_CONFIDENCE_AUTO_INJECT: float = 0.5   # 自动注入门槛
```

不保留旧别名 `MIN_CONFIDENCE`——避免调用方误用导致阈值语义模糊。

### 6.2 职责分层

| 函数 / 类 | 阈值 | 路径 |
|---|---|---|
| `_keep_record()`（`retrieval.py:25` 起） | `confidence >= MIN_CONFIDENCE_HARD` | 所有路径共用 |
| `MemorySectionAssembler.assemble()` 内嵌 `_keep`（`retrieval.py:180` 起） | 额外加 `confidence >= MIN_CONFIDENCE_AUTO_INJECT` | 仅 `context_injection` |

### 6.3 过滤流程

```
Store 查询结果
    │
    ▼
_keep_record(record, context)
    │
    ├─ confidence < 0.3  → 丢 (硬线)
    ├─ do_not_auto_inject tag + access_purpose=context_injection → 丢
    ├─ status / valid_from / valid_until / scope / owner_only 等 → 丢
    │
    ▼ （到这里的记录硬线过了）
    │
    ▼
MemorySectionAssembler.assemble(access_purpose=...)
    │
    ▼ 内嵌 _keep：
    │
    ├─ access_purpose == "context_injection" && confidence < 0.5 → 丢
    │
    ▼
最终注入 / 工具返回
```

### 6.4 设计理由

- Spec §7.3 明文规定 `0.3` 是绝对过滤线、`0.5` 是注入门槛，二者并存
- Spec §9.3 同步明确：`[0.3, 0.5)` 的记录"不自动注入；仍可被 `memory_search` 工具显式检索"
- 分两层实现让"硬线归过滤器、注入门槛归 assembler" 职责清晰——assembler 本来就只服务 auto-inject 路径

---

## 7. B3 — Planner 词库与分词升级

### 7.1 总体方案

| 维度 | 现状 | 改后 |
|---|---|---|
| 存储结构 | `list[str]` | `frozenset[str]` |
| 匹配方式 | `substring in` | `jieba.lcut()` 分词 → `set & set` |
| 触发判定复杂度 | O(n_message × n_keywords) substring | O(n_tokens) hash lookup |
| 词库位置 | `retrieval.py` 模块级常量 | 独立文件 `sebastian/memory/retrieval_lexicon.py` |
| Relation lane 私有名 | 不支持 | Entity Registry 启动时合并 + 写入时 reload |
| 是否引入 LLM | 否 | 仍为否 |

### 7.2 为什么用 `jieba.lcut()` 而不是 `jieba.cut_for_search()`

实测结果：

| 输入 | `cut_for_search` | `lcut`（精确） |
|---|---|---|
| "推荐信" | `['推荐', '推荐信']` ❌ 拆出 `推荐` | `['推荐信']` ✅ |
| "我需要一封推荐信" | `['我', '需要', '一封', '推荐', '推荐信']` ❌ | `['我', '需要', '一封', '推荐信']` ✅ |

`cut_for_search` 为 FTS 召回设计——**主动对长词再切分**以提高召回率。对意图判断是反向副作用：会把合法名词短语误拆成触发词。

意图分词的目标是**精度**（是否正确命中用户意图），不是召回；FTS 索引侧的目标才是召回。两侧目标不同，分词策略不同：

- **意图分词（本 spec）**：`jieba.lcut()` 精确模式
- **FTS 索引**（`retrieval.md §5`）：`jieba.cut_for_search()` 搜索模式

两者在同一进程内共存，各取所需。

### 7.3 词库文件结构

新增 `sebastian/memory/retrieval_lexicon.py`：

```python
from __future__ import annotations

# Profile Lane — 画像/偏好/稳定身份的触发语
PROFILE_LANE_WORDS: frozenset[str] = frozenset({
    # 自指代词
    "我", "我的", "本人",
    # 偏好动词
    "喜欢", "偏好", "爱好", "讨厌", "不喜欢", "prefer", "like", "hate",
    # 身份陈述
    "是", "am", "i", "i'm", "我是",
    # 隐式偏好意图
    "推荐", "推荐个", "推荐一个", "建议", "觉得", "认为",
    "recommend", "suggest", "think",
    # ...（完整词表见 §7.4）
})

# Context Lane — 当前时间/动态性副词与进展询问
CONTEXT_LANE_WORDS: frozenset[str] = frozenset({
    "现在", "今天", "最近", "这两天", "本周", "这周", "目前", "正在",
    "now", "today", "recent", "currently", "this week",
    "进展", "怎么样", "如何", "到哪了",
    "status", "progress",
    # ...
})

# Episode Lane — 历史回忆触发语
EPISODE_LANE_WORDS: frozenset[str] = frozenset({
    "上次", "之前", "以前", "曾经", "记得", "回忆", "回顾",
    "last time", "previously", "before", "remember", "recall",
    "讨论过", "说过", "聊过", "提过",
    # ...
})

# Relation Lane — 静态部分：通用称谓
RELATION_LANE_STATIC_WORDS: frozenset[str] = frozenset({
    # 家庭
    "老婆", "妻子", "太太", "爱人", "老公", "丈夫",
    "孩子", "儿子", "女儿", "宝宝",
    "爸爸", "妈妈", "父母",
    "wife", "husband", "kid", "son", "daughter",
    # 工作
    "同事", "老板", "下属", "项目", "团队",
    "colleague", "team", "project", "boss",
    # ...
})

# Small-talk 短路词
SMALL_TALK_WORDS: frozenset[str] = frozenset({
    "hi", "hello", "hey",
    "你好", "嗨",
    "ok", "好的", "谢谢", "thanks", "thank",
    "嗯", "行",
})
```

### 7.4 词表定稿条件

本 spec 给出**初版**词库大纲（上节示例）。实施阶段要求：

1. 每条 lane 的词库总量 ≥ 30 条
2. 中英文平衡（英文触发词覆盖以防中英混合输入）
3. 词库变更须连带更新 `test_retrieval_lexicon.py` 的覆盖样本

### 7.5 Entity Registry 现状与必要新增

#### 7.5.1 现状

`sebastian/memory/entity_registry.py` `EntityRegistry` 类现有方法：

| 方法 | 作用 |
|---|---|
| `upsert_entity(canonical_name, entity_type, aliases, metadata)` | **唯一写入入口**；同名实体自动合并 aliases（改名就是 upsert 新 canonical_name） |
| `lookup(text)` | 按 canonical_name 或 aliases 反查实体 |
| `list_relations(subject_id, limit)` | 返回 relation 候选 |
| `snapshot(limit=64)` | 最近创建的 N 个实体，用于 consolidator 预览 |
| `sync_jieba_terms()` | 把全部 canonical_name + aliases 注册进 jieba 用户词典 |

关键观察：
- **写入入口只有 `upsert_entity` 一个**（删除当前未实现）
- `sync_jieba_terms()` 已经在做"读出全量实体名 → 灌入 jieba"——意味着我们 B3 的"读出全量实体名 → 放 Planner trigger set" 是**并列同型**的操作，可以提取共用实现

#### 7.5.2 本 spec 新增的 `EntityRegistry` 方法

新增一个纯读取接口，让 `sync_jieba_terms()` 和 Planner 共用：

```python
# sebastian/memory/entity_registry.py — 新增
async def list_all_names_and_aliases(self) -> list[str]:
    """Return all canonical_names and aliases as a flat list.

    Used by sync_jieba_terms() and MemoryRetrievalPlanner.bootstrap_entity_triggers().
    """
    result = await self._session.scalars(select(EntityRecord))
    names: list[str] = []
    for record in result.all():
        names.append(record.canonical_name)
        names.extend(record.aliases)
    return names
```

同时重构 `sync_jieba_terms()` 复用该方法（不改外部行为）：

```python
async def sync_jieba_terms(self) -> None:
    terms = await self.list_all_names_and_aliases()
    add_entity_terms(terms)
```

本改动**仅为暴露已有的读取能力**，不涉及写逻辑。

### 7.6 Planner 匹配逻辑

`MemoryRetrievalPlanner.plan()` 改写：

```python
from sebastian.memory.retrieval_lexicon import (
    PROFILE_LANE_WORDS,
    CONTEXT_LANE_WORDS,
    EPISODE_LANE_WORDS,
    RELATION_LANE_STATIC_WORDS,
    SMALL_TALK_WORDS,
)

class MemoryRetrievalPlanner:
    def __init__(self) -> None:
        # 启动默认只有静态词；bootstrap 后会合并 Entity Registry
        self._relation_trigger_set: frozenset[str] = RELATION_LANE_STATIC_WORDS

    async def bootstrap_entity_triggers(self, registry: EntityRegistry) -> None:
        """启动期调用，把 Entity Registry 的所有 name/aliases 合并进 relation 触发词。"""
        entity_names = await registry.list_all_names_and_aliases()
        self._relation_trigger_set = RELATION_LANE_STATIC_WORDS | frozenset(entity_names)

    async def reload_entity_triggers(self, registry: EntityRegistry) -> None:
        """Entity Registry 写入后调用，刷新触发词缓存。"""
        await self.bootstrap_entity_triggers(registry)

    def plan(self, context: RetrievalContext) -> RetrievalPlan:
        msg = context.user_message.lower().strip()
        if not msg:
            return RetrievalPlan(profile_lane=False, context_lane=False,
                                 episode_lane=False, relation_lane=False)

        tokens: set[str] = set(jieba.lcut(msg))

        # Small-talk 短路
        if tokens & SMALL_TALK_WORDS and len(tokens) <= 3:
            return RetrievalPlan(profile_lane=False, context_lane=False,
                                 episode_lane=False, relation_lane=False)

        return RetrievalPlan(
            profile_lane=bool(tokens & PROFILE_LANE_WORDS),
            context_lane=bool(tokens & CONTEXT_LANE_WORDS),
            episode_lane=bool(tokens & EPISODE_LANE_WORDS),
            relation_lane=bool(tokens & self._relation_trigger_set),
        )
```

注：`bootstrap_entity_triggers` / `reload_entity_triggers` 是 `async` 方法（`list_all_names_and_aliases` 是协程）；调用侧需在 async 上下文中使用。

### 7.7 Entity Registry 合并时机

**策略**：启动缓存 + `upsert_entity` 末尾显式 reload（**不走** event bus）。

#### 7.7.1 启动 bootstrap

Gateway 初始化期（靠近现有 `SlotRegistry.bootstrap_from_db` 与 `sync_jieba_terms` 调用位置）新增：

```python
# sebastian/gateway/lifecycle.py（或现有 memory bootstrap 集中处）
await registry.sync_jieba_terms()
await planner.bootstrap_entity_triggers(registry)
```

#### 7.7.2 写入路径 reload

`EntityRegistry.upsert_entity` 当前是**唯一**写入入口；在该方法末尾（`await self._session.flush()` 之后、return 之前）追加：

```python
async def upsert_entity(self, ...) -> EntityRecord:
    # ... existing logic ...
    await self._session.flush()

    # 新增：同步触发词缓存（如果 planner 注入了）
    if self._planner is not None:
        await self._planner.reload_entity_triggers(self)
    # 同时可考虑顺便 sync_jieba_terms（本 spec 不强制，由实施阶段判断）

    return record_or_existing
```

**依赖注入**：`EntityRegistry.__init__` 接受可选 `planner: MemoryRetrievalPlanner | None = None`；调用路径在初始化时传入 planner 实例；`None` 时跳过 reload（给测试和不需要触发词缓存的独立调用用）。

#### 7.7.3 为什么不实现 `rename_entity` / `delete_entity` 专用钩子

当前 `EntityRegistry` 没有独立的 rename / delete 方法。改名通过 `upsert_entity` 合并 aliases 实现，删除场景不存在。写入入口收敛到 `upsert_entity` 一个，reload 挂一次即可，无需预留将来可能新增的 rename/delete 入口——未来若新增，同步挂 reload 是自然扩展。

#### 7.7.4 为什么不用 event bus

- 订阅方只有 planner 一个（不会有第二个）
- 发布方只有 `upsert_entity` 一个
- 加发布-订阅抽象是典型的过度设计，与 CLAUDE.md "最短路径" 原则冲突
- 一旦将来出现多订阅方的真实需求，重构为 event bus 的代价远低于现在的"未来可能需要"预算

### 7.8 两层门控关系（实现指引，不改行为）

B3 是 **Planner 层（是否激活 lane）** 的改动，**不改 Store 层（如何召回）**：

| Lane | Planner 层（本 spec 改） | Store 层（本 spec 不改） |
|---|---|---|
| Profile | 关键词激活 | 按 confidence + recency 排，无 query 匹配 |
| Context | 关键词激活 | FTS + jieba 按 query 命中度排，无命中降级为 confidence + recency |
| Episode | 关键词激活 | FTS + jieba 按 query 命中度排，无 terms 返回 `[]` |
| Relation | 关键词（含 Entity 名）激活 | 按 query 中的实体名定向查 |

---

## 8. 集成方式

三项改动执行顺序与触点：

```
用户消息到达
        │
        ▼
BaseAgent._stream_inner()
        │
        ▼
_memory_section(session_id, agent_context, user_message)
   ┌────────────────────────────────────────┐
   │ [B1] depth != 1 → return ""           │  ← 守卫（§5）
   └────────────────────────────────────────┘
        │
        ▼
Planner.plan(context)
   ┌────────────────────────────────────────┐
   │ [B3] tokens = set(jieba.lcut(msg))    │  ← 精确分词（§7.2 / §7.5）
   │ [B3] tokens & *_LANE_WORDS → 激活      │  ← O(1) 查表
   │ [B3] tokens & _relation_trigger_set →  │  ← 含 Entity Registry 动态词（§7.6）
   └────────────────────────────────────────┘
        │
        ▼
各 Lane Store 查询（profile / context / episode / relation）
        │
        ▼
_keep_record(record, context)
   ┌────────────────────────────────────────┐
   │ [B2] confidence < 0.3 → 丢（硬线）     │  ← §6.2
   │      do_not_auto_inject / status ...   │  ← 已有逻辑，不改
   └────────────────────────────────────────┘
        │
        ▼
MemorySectionAssembler.assemble(..., access_purpose)
   ┌────────────────────────────────────────┐
   │ [B2] access_purpose == context_inject  │  ← §6.2
   │      && confidence < 0.5 → 丢           │
   └────────────────────────────────────────┘
        │
        ▼
返回 system-prompt 记忆段
```

三项改动无共享状态，互相独立，可分 task 实施。

---

## 9. Pinned 清理（配套动作）

本 spec 不实现 `pinned` 豁免（见 §13），但需清理现有代码与文档里会诱导后来者"随手补"的痕迹：

| # | 文件 | 动作 |
|---|---|---|
| 1 | `sebastian/memory/prompts.py:152` | `policy_tags \| array<string> \| 一般 []；"pinned" 表示钉住` → `policy_tags \| array<string> \| 一般 []，不要主动设置任何值` |
| 2 | `docs/superpowers/specs/2026-04-20-dynamic-slot-system-design.md:518` | 同上措辞调整 |
| 3 | `docs/superpowers/plans/2026-04-20-dynamic-slot-system.md:1422` | 同上措辞调整 |
| 4 | `docs/architecture/spec/memory/retrieval.md §7.4` | 从 "实现状态：`pinned` 豁免逻辑当前尚未在 `MemorySectionAssembler` 中实现，为**待补功能**。实现时应在 assembler 中先单独收集..." 改为："**实现状态**：`pinned` 豁免逻辑为**独立未来 spec** 范围，当前 Retrieval Fixes spec（`docs/superpowers/specs/2026-04-20-memory-retrieval-fixes-design.md`）明确**不实现**。任何 pinned 相关代码改动必须等独立 spec 批准。" |
| 5 | `docs/architecture/spec/memory/artifact-model.md §10.1/§10.2/§10.3` | **保留不动**（这是设计档案里的前置约束） |

---

## 10. 测试期望

### 10.1 B1 — depth 守卫（`tests/unit/memory/test_memory_section_depth_guard.py`，新增）

| 测试 | 前置 | 期望 |
|---|---|---|
| `test_depth_1_injects_memory` | `self._current_depth[sid] = 1` | 返回非空记忆段 |
| `test_depth_2_returns_empty` | `self._current_depth[sid] = 2` | 返回 `""` |
| `test_depth_missing_returns_empty` | `self._current_depth` 无此 `sid` | 返回 `""` |
| `test_depth_zero_returns_empty` | `self._current_depth[sid] = 0` | 返回 `""` |

### 10.2 B2 — confidence 双阈值（`tests/unit/memory/test_retrieval_filter.py`，扩展）

| 测试 | 前置 | 期望 |
|---|---|---|
| `test_hard_gate_drops_below_0_3` | confidence=0.25 | 任何路径 `_keep_record` 返回 False |
| `test_hard_gate_passes_at_0_3` | confidence=0.3 | `_keep_record` 返回 True |
| `test_auto_inject_drops_mid_band` | confidence=0.35, purpose=`context_injection` | Assembler 丢弃 |
| `test_tool_search_keeps_mid_band` | confidence=0.35, purpose=`tool_search` | Assembler 保留 |
| `test_auto_inject_keeps_above_gate` | confidence=0.55, purpose=`context_injection` | Assembler 保留 |

### 10.3 B3 — 词库与分词（`tests/unit/memory/test_retrieval_lexicon.py`，新增）

| 测试 | 输入 | 期望激活 lane |
|---|---|---|
| `test_recommendation_letter_not_trigger_profile` | "我需要一封推荐信" | Profile Lane **不**激活（验证 `jieba.lcut` 不误拆） |
| `test_recommend_verb_triggers_profile` | "给我推荐一个餐厅" | Profile Lane 激活 |
| `test_remember_triggers_episode` | "你还记得我说过的项目吗" | Episode Lane 激活 |
| `test_recent_triggers_context` | "最近进展怎么样" | Context Lane 激活 |
| `test_relation_static_word_triggers` | "我老婆今天做了饭" | Relation Lane 激活 |
| `test_small_talk_short_circuits_all_lanes` | "hi" | 所有 lane 均不激活 |
| `test_empty_message_no_activation` | "" | 所有 lane 均不激活 |

### 10.4 B3 — Entity bootstrap / reload（`tests/unit/memory/test_planner_entity_bootstrap.py`，新增）

| 测试 | 前置 | 期望 |
|---|---|---|
| `test_bootstrap_merges_entity_names` | EntityRegistry 含 canonical_name=`小美` / `豆豆` | `planner._relation_trigger_set` 含两者 + 静态词 |
| `test_bootstrap_merges_aliases` | canonical_name=`小美`，aliases=`["美美", "小美同学"]` | 三者都在 trigger_set |
| `test_entity_name_activates_relation_lane` | bootstrap 后，输入 "小美今天做了饭" | Relation Lane 激活 |
| `test_alias_activates_relation_lane` | bootstrap 后，输入 "美美来了" | Relation Lane 激活（验证 aliases 同样生效） |
| `test_reload_reflects_new_entity` | bootstrap → EntityRegistry upsert 新实体 "王总" → 调用 `reload_entity_triggers` | "王总来找我" 激活 relation |
| `test_reload_reflects_added_alias` | 原实体 upsert 新增 alias → reload | 新 alias 立即命中 |
| `test_bootstrap_not_called_static_only` | 未 bootstrap | `_relation_trigger_set == RELATION_LANE_STATIC_WORDS` |

### 10.5 B3 — Entity 写入触发 reload（`tests/integration/memory/test_entity_registry_reload_hook.py`，新增）

| 测试 | 前置 | 期望 |
|---|---|---|
| `test_upsert_new_entity_triggers_reload` | `EntityRegistry` 构造时传入 planner mock | `upsert_entity(canonical_name="王总", ...)` 后 `planner.reload_entity_triggers` 被调 1 次 |
| `test_upsert_existing_entity_merging_aliases_triggers_reload` | 同上，先 upsert 一次 | 再次 upsert 合并 aliases 时仍调用 reload（改名场景） |
| `test_none_planner_skips_reload` | `EntityRegistry(planner=None)` | `upsert_entity` 不报错，无 reload 调用 |
| `test_reload_reflects_after_bootstrap` | planner bootstrap 后，upsert 新实体 | 新实体名进入 `planner._relation_trigger_set` |

### 10.6 Pinned 清理（`tests/unit/memory/test_prompts.py`，新增或扩展）

| 测试 | 期望 |
|---|---|
| `test_extractor_prompt_no_pinned_example` | 渲染后的 Extractor prompt 字符串不含 `"pinned"`（大小写不敏感） |

### 10.7 回归基线

- `pytest tests/` 全绿（所有现有 memory 测试不回归）
- `mypy sebastian/` 0 error
- `ruff check sebastian/ tests/` 0 warning
- `ruff format --check sebastian/ tests/` 无格式差

---

## 11. 验收标准

全部满足才算完成：

| # | 标准 | 验证 |
|---|---|---|
| 1 | `depth != 1` 的子 agent `_memory_section()` 返回空字符串 | §10.1 单测 |
| 2 | `depth` 未初始化（None）时返回空字符串 | §10.1 单测 |
| 3 | `context_injection` 路径丢弃 confidence ∈ [0.3, 0.5) 的记录 | §10.2 单测 |
| 4 | `tool_search` 路径仍返回 confidence ∈ [0.3, 0.5) 的记录 | §10.2 单测 |
| 5 | 任何路径丢弃 confidence < 0.3 的记录 | §10.2 单测 |
| 6 | "推荐信" 类长词不触发 lane 误判 | §10.3 单测 |
| 7 | Entity Registry 里的用户私有名字能命中 Relation Lane | §10.4 单测 |
| 8 | Entity 新增 / 改名 / 删除后，下一轮对话立即生效 | §10.5 集成测试 |
| 9 | Extractor LLM prompt 不再含 `"pinned"` 引导字样 | §10.6 单测 |
| 10 | 旧 `MIN_CONFIDENCE` 常量在代码中完全删除（grep 验证） | 手动 `rg MIN_CONFIDENCE sebastian/` 返回 0 结果 |
| 11 | 所有现有 memory 测试不回归 | §10.7 |
| 12 | `mypy` / `ruff` 全绿 | §10.7 |
| 13 | `docs/architecture/spec/memory/retrieval.md §7.4` 状态段更新为 "不实现" 措辞 | 手动检查 |

---

## 12. 实施顺序建议

分 6 组（实施时可拆成独立 task）。依赖关系：

```
G1 ──► G2 ──► G3         (B3 链，线性依赖)
G4 (独立)                 (B2)
G5 (独立)                 (B1)
G6 (收尾，依赖 G1 完成)
```

1. **G1** — 新增 `sebastian/memory/retrieval_lexicon.py`，5 个 `frozenset` 词库落定（§7.3 / §7.4）；B3 词库单测（§10.3 子集）
2. **G2（依赖 G1）** — 改 `MemoryRetrievalPlanner.plan()` 用 `jieba.lcut` + set 交集（§7.6）；补齐 §10.3 分词精度单测
3. **G3（依赖 G2）** — `EntityRegistry.list_all_names_and_aliases()` 新增；Planner `bootstrap_entity_triggers` / `reload_entity_triggers`；`EntityRegistry.__init__` 接 planner 注入；`upsert_entity` 末尾挂 reload（§7.5 / §7.7）；§10.4 / §10.5 测试
4. **G4（独立）** — `retrieval.py` 拆 `MIN_CONFIDENCE` 为两个常量；`_keep_record` 走硬线；Assembler 内嵌 `_keep` 加 0.5 门槛（§6）；§10.2 测试
5. **G5（独立）** — `_memory_section()` 顶部加 depth 守卫（§5）；§10.1 测试
6. **G6（收尾，依赖 G1 完成）** — Pinned 清理（5 处，§9）；§10.6 测试；更新 `retrieval.md §7.4` 状态段

**并行性**：G4 与 G5 与 G1 之间相互独立，三者可并行启动；G2 等 G1，G3 等 G2；G6 等 G1（因为要改 `prompts.py`，和 G1 的词库文件在相邻模块但无直接代码冲突，可放宽为"不强制等"）。

---

## 13. Non-goals 详细声明（禁止后来者随手补）

### 13.1 `pinned` 豁免 budget（原 B4）

**设计语义**已在以下处定义完整：
- `docs/architecture/spec/memory/retrieval.md §7.4`
- `docs/architecture/spec/memory/artifact-model.md §10.1 / §10.2 / §10.3`

**本 spec 明确不实现**，理由：

1. `pinned` 唯一有效作用是"豁免 lane limit"，仅当用户已 pin 超过 lane 默认额度（如 `profile_limit=5`）时才产生实际差异
2. Spec §10.2 规定 `pinned` 只能由**用户 UI** 设置，LLM Extractor / System 代码均不可设置
3. 当前 Android App / Web UI **均无记忆管理界面**，无 pin/unpin 交互入口
4. 无写入路径 → 数据库永远不存在 `pinned` 记录 → 豁免代码永远不会触发 → dead code
5. 没有真实触发场景，黑盒测试只能人工 `INSERT` 伪造数据，实现对错无法验证

**触发重新开 spec 的条件**：

- 用户明确提出 pin 功能需求
- **且** 对应 UI 入口（Android / Web）的交互设计同步敲定
- 届时作为独立 spec 同步设计**读路径豁免**与**写路径入口**，不在 Retrieval Fixes 范围内增量实现

**禁止动作**：

- 不允许在本 spec 实施期间或之后，基于"Spec §7.4 里写了" 或 "顺手补一下" 的理由，独立添加豁免代码
- 不允许以 `policy_tags` 字段"顺便支持"为名，在 Assembler 中预留 pinned 分支
- 任何 pinned 相关改动必须等独立 spec 批准

### 13.2 不引入 LLM 做意图判断

本 spec 经过评估 A/B/C/D 四种方案后选择纯关键词（§7）。不得以"更智能"为由把 `MemoryRetrievalPlanner` 改成 LLM 调用：

- 读路径是同步阻塞，每轮首 token 延迟 +200ms 是项目不接受的
- 关键词 + Entity Registry 动态合并覆盖 ~90%+ 真实意图场景
- 如真需要更高精度，应独立开 spec 讨论异步意图判断架构，不在本 spec 增量

### 13.3 不改写路径

本 spec 对 `sebastian/memory/entity_registry.py` 的所有改动仅限：

- **新增** `list_all_names_and_aliases()` 纯读取方法（内部把 `sync_jieba_terms` 原有的读取逻辑提取复用）
- **新增** `__init__` 的可选 `planner` 注入参数
- **在** `upsert_entity` 末尾 `await self._session.flush()` 之后追加 1 行 `reload` 调用

这些是"读缓存同步" + "只读接口暴露"，**不涉及** Memory 写逻辑的语义变更（Extractor / Consolidator / Resolver / WriteRouter / 任何 artifact 写路径一律不动）。

不实现 `rename_entity` / `delete_entity` 方法（当前 codebase 没有这两个入口）；若未来新增，应同步挂 `reload_entity_triggers` 调用。

### 13.4 不引入 event bus 驱动 Entity 变更同步

见 §7.6.3。只有一个订阅方 + 一个发布方时，发布-订阅是过度设计。未来出现多订阅方时再重构。

### 13.5 不处理 `memory_search(min_confidence=...)` 工具参数

Spec §7.3 脚注提到工具可传 `min_confidence` 覆盖默认硬线。本 spec 不实现这个参数：

- 当前 `memory_search` 工具调用方无需更低阈值
- 若未来有需求，在工具层处理（工具入口直接收参传给 store），不下沉到 retrieval.py 的模块常量

---

## 14. 参考资料

- `docs/architecture/spec/memory/INDEX.md` — Memory 系统总览
- `docs/architecture/spec/memory/retrieval.md` — 读路径架构 Spec（§3 Planner / §4 Lane / §7 Budget / §7.3 confidence 阈值）
- `docs/architecture/spec/memory/artifact-model.md` — Artifact 协议（§9.3 confidence 阈值规则 / §10.1 policy_tags 语义 / §10.4 agent 层级访问边界）
- `sebastian/memory/data-flow.md` — 当前读写数据流
- `sebastian/memory/retrieval.py` — 现状实现
- `sebastian/core/base_agent.py` — `_memory_section()` 与 `_current_depth` 维护

---

*← 返回 [Specs 索引](./INDEX.md)*
