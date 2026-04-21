# Memory Retrieval Path Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Memory 自动注入链路上的三处与 Spec 不一致实现（depth 守卫 / confidence 双阈值 / Planner 词库升级），并清理 LLM prompt 里诱导 `pinned` 的字样。

**Architecture:** 三项改动互相独立，共用同一份 Planner 单例。B1 在 `_memory_section()` 顶部 fail-closed 守卫；B2 把 `MIN_CONFIDENCE` 拆成硬线 + 注入门槛两级，分别归 `_keep_record` 与 `MemorySectionAssembler._keep`；B3 新增 `retrieval_lexicon.py` 词库，Planner 用 `jieba.lcut` 精确分词 + `set & frozenset` O(1) 命中，Entity Registry 启动 bootstrap + 写入末尾 reload 让私有实体名动态并入触发词。

**Tech Stack:** Python 3.12+、SQLAlchemy async、jieba 精确分词、pytest + pytest-asyncio、SQLite FTS5。

**Spec**: [docs/superpowers/specs/2026-04-20-memory-retrieval-fixes-design.md](../specs/2026-04-20-memory-retrieval-fixes-design.md)

---

## 文件结构

**新增**：
- `sebastian/memory/retrieval_lexicon.py` — 5 个 `frozenset` 词库（Profile / Context / Episode / Relation-static / Small-talk）
- `tests/unit/memory/test_retrieval_lexicon.py` — 词库匹配与 `jieba.lcut` 精度单测
- `tests/unit/memory/test_memory_section_depth_guard.py` — B1 depth 守卫单测
- `tests/unit/memory/test_planner_entity_bootstrap.py` — Planner bootstrap/reload 单测
- `tests/integration/memory/test_entity_registry_reload_hook.py` — `upsert_entity` 触发 reload 集成测试

**修改**：
- `sebastian/memory/retrieval.py` — 删 `MIN_CONFIDENCE` + 4 个 `*_LANE_KEYWORDS`；引入 `MIN_CONFIDENCE_HARD` / `MIN_CONFIDENCE_AUTO_INJECT`；`_keep_record` 用硬线；`MemorySectionAssembler._keep` 加注入门槛；`MemoryRetrievalPlanner` 改用 `jieba.lcut` + set；新增模块级 `DEFAULT_RETRIEVAL_PLANNER` 单例；`retrieve_memory_section` 改用单例
- `sebastian/memory/entity_registry.py` — 新增 `list_all_names_and_aliases()`；`__init__` 加可选 `planner` 注入；`upsert_entity` 末尾调 `planner.reload_entity_triggers`；`sync_jieba_terms` 重构复用新方法
- `sebastian/gateway/app.py` — 启动期调 `DEFAULT_RETRIEVAL_PLANNER.bootstrap_entity_triggers()`
- `sebastian/core/base_agent.py:236` — `_memory_section()` 顶部加 depth 守卫
- `sebastian/memory/prompts.py:152` — pinned 字样改为"不要主动设置任何值"
- `docs/architecture/spec/memory/retrieval.md §7.4` — 更新实现状态为"不实现"
- `docs/superpowers/specs/2026-04-20-dynamic-slot-system-design.md:518` — 同步 pinned 字样
- `docs/superpowers/plans/2026-04-20-dynamic-slot-system.md:1422` — 同步 pinned 字样
- `tests/unit/memory/test_retrieval_filter.py` — 扩展双阈值用例
- `tests/unit/memory/test_prompts.py` — 新增/扩展：prompt 不含 `pinned`

**不改**：写路径任何代码、`ToolCallContext.depth` 默认值（base_agent.py:555）、event bus 抽象、`artifact-model.md §10.x`（前置设计档案）。

---

## 依赖 & 实施顺序

```
Task 1 (词库文件) ──► Task 2 (Planner jieba+singleton) ──► Task 3 (EntityRegistry+Planner bootstrap/reload) ──► Task 4 (gateway startup wire)
Task 5 (B2 双阈值)    独立
Task 6 (B1 depth 守卫) 独立
Task 7 (Pinned 清理)   独立（可最后做）
```

Task 1/5/6/7 之间互相独立，可并行。Task 2 等 Task 1，Task 3 等 Task 2，Task 4 等 Task 3。

---

## Task 1: 新增 `retrieval_lexicon.py` 词库文件

**Files:**
- Create: `sebastian/memory/retrieval_lexicon.py`
- Create: `tests/unit/memory/test_retrieval_lexicon.py`

- [ ] **Step 1: 写失败测试（词库存在性 + 基本断言）**

`tests/unit/memory/test_retrieval_lexicon.py`:

```python
from __future__ import annotations

from sebastian.memory.retrieval_lexicon import (
    CONTEXT_LANE_WORDS,
    EPISODE_LANE_WORDS,
    PROFILE_LANE_WORDS,
    RELATION_LANE_STATIC_WORDS,
    SMALL_TALK_WORDS,
)


def test_all_lexicons_are_frozensets() -> None:
    for lex in (
        PROFILE_LANE_WORDS,
        CONTEXT_LANE_WORDS,
        EPISODE_LANE_WORDS,
        RELATION_LANE_STATIC_WORDS,
        SMALL_TALK_WORDS,
    ):
        assert isinstance(lex, frozenset)
        assert len(lex) >= 30, f"lexicon too small: {len(lex)}"


def test_profile_lexicon_covers_preference_verbs() -> None:
    assert "喜欢" in PROFILE_LANE_WORDS
    assert "偏好" in PROFILE_LANE_WORDS
    assert "prefer" in PROFILE_LANE_WORDS


def test_context_lexicon_covers_time_adverbs() -> None:
    assert "现在" in CONTEXT_LANE_WORDS
    assert "最近" in CONTEXT_LANE_WORDS
    assert "now" in CONTEXT_LANE_WORDS


def test_episode_lexicon_covers_recall_verbs() -> None:
    assert "上次" in EPISODE_LANE_WORDS
    assert "记得" in EPISODE_LANE_WORDS
    assert "remember" in EPISODE_LANE_WORDS


def test_relation_static_covers_family_terms() -> None:
    for term in ("老婆", "妻子", "太太", "爱人"):
        assert term in RELATION_LANE_STATIC_WORDS
    assert "同事" in RELATION_LANE_STATIC_WORDS


def test_small_talk_covers_greetings() -> None:
    assert "hi" in SMALL_TALK_WORDS
    assert "你好" in SMALL_TALK_WORDS
    assert "thanks" in SMALL_TALK_WORDS
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/memory/test_retrieval_lexicon.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sebastian.memory.retrieval_lexicon'`

- [ ] **Step 3: 实现词库文件**

`sebastian/memory/retrieval_lexicon.py`:

```python
"""Intent-classification lexicons for MemoryRetrievalPlanner.

Each lane has a frozenset of trigger words matched against
``jieba.lcut(user_message.lower())`` tokens. See spec §7 of
docs/superpowers/specs/2026-04-20-memory-retrieval-fixes-design.md
for rationale.
"""

from __future__ import annotations

# Profile Lane — 画像/偏好/稳定身份触发语
PROFILE_LANE_WORDS: frozenset[str] = frozenset(
    {
        # 自指代词
        "我", "我的", "本人", "自己",
        # 偏好动词
        "喜欢", "偏好", "爱好", "讨厌", "不喜欢", "讨厌的", "最爱",
        "prefer", "like", "love", "hate", "dislike", "favorite",
        # 身份陈述
        "是", "我是", "am", "i", "i'm", "my", "mine",
        # 隐式偏好意图（推荐/建议类动词）
        "推荐", "建议", "觉得", "认为", "想要", "希望",
        "recommend", "suggest", "think", "believe", "want", "wish",
        # 口味/性格描述
        "口味", "风格", "习惯", "性格", "脾气",
        "style", "habit", "taste", "personality",
    }
)

# Context Lane — 当前时间/动态性副词与进展询问
CONTEXT_LANE_WORDS: frozenset[str] = frozenset(
    {
        # 时间指示
        "现在", "今天", "最近", "这两天", "本周", "这周", "目前",
        "当前", "正在", "此刻", "今晚", "今早", "今晨",
        "now", "today", "tonight", "currently", "recent", "recently",
        "this", "week",
        # 进展询问
        "进展", "进度", "情况", "状态", "怎么样", "如何", "到哪了",
        "status", "progress", "update", "how",
        # 正在做
        "在做", "在忙", "在干",
        "doing", "working",
    }
)

# Episode Lane — 历史回忆触发语
EPISODE_LANE_WORDS: frozenset[str] = frozenset(
    {
        # 时间回指
        "上次", "之前", "以前", "曾经", "那时", "当时",
        "last", "previously", "before", "earlier", "ago",
        # 回忆动词
        "记得", "想起", "回忆", "回顾", "忘了", "忘记",
        "remember", "recall", "forgot", "forget", "reminded",
        # 历史讨论
        "讨论过", "说过", "聊过", "提过", "讲过",
        "discussed", "mentioned", "said", "told",
        # 过往事件
        "那次", "那天", "那一次",
        "that", "time",
    }
)

# Relation Lane — 静态通用称谓（动态部分由 Entity Registry 运行期合并）
RELATION_LANE_STATIC_WORDS: frozenset[str] = frozenset(
    {
        # 家庭
        "老婆", "妻子", "太太", "爱人", "老公", "丈夫", "伴侣",
        "孩子", "儿子", "女儿", "宝宝", "娃",
        "爸爸", "妈妈", "父母", "爸", "妈", "父亲", "母亲",
        "哥哥", "姐姐", "弟弟", "妹妹", "兄弟", "姐妹",
        "wife", "husband", "kid", "kids", "son", "daughter",
        "dad", "mom", "father", "mother", "parent", "parents",
        "brother", "sister", "sibling",
        # 工作
        "同事", "老板", "下属", "上司", "领导", "队友",
        "项目", "团队", "小组",
        "colleague", "coworker", "team", "teammate",
        "project", "boss", "manager", "lead",
        # 社交
        "朋友", "好友", "伙伴", "邻居",
        "friend", "buddy", "partner", "neighbor",
        # 宠物
        "宠物", "猫", "狗", "小猫", "小狗",
        "pet", "cat", "dog",
    }
)

# Small-talk 短路词（tokens & SMALL_TALK_WORDS 且 len(tokens) <= 3 → 所有 lane 关闭）
SMALL_TALK_WORDS: frozenset[str] = frozenset(
    {
        # 英文问候
        "hi", "hello", "hey", "yo", "sup",
        "morning", "evening", "night",
        # 中文问候
        "你好", "您好", "嗨", "哈喽",
        "早", "早上好", "晚上好", "晚安",
        # 确认/致谢
        "ok", "okay", "好", "好的", "行", "嗯", "收到",
        "谢谢", "多谢", "感谢",
        "thanks", "thank", "thx", "ty",
        # 告别
        "bye", "再见", "拜拜",
    }
)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/memory/test_retrieval_lexicon.py -v`
Expected: PASS — 所有 5 个测试通过。

- [ ] **Step 5: Lint 检查**

Run: `ruff check sebastian/memory/retrieval_lexicon.py tests/unit/memory/test_retrieval_lexicon.py`
Expected: All checks passed.

Run: `ruff format sebastian/memory/retrieval_lexicon.py tests/unit/memory/test_retrieval_lexicon.py`
Expected: 无格式差或自动格式化后无新差异。

- [ ] **Step 6: Commit**

```bash
git add sebastian/memory/retrieval_lexicon.py tests/unit/memory/test_retrieval_lexicon.py
git commit -m "feat(memory): 新增 retrieval_lexicon 词库文件（B3 词库落定）

5 个 frozenset 词库：Profile / Context / Episode / Relation-static / Small-talk。
每条 lane ≥30 词，中英平衡，覆盖自指代、偏好动词、时间副词、回忆动词、
家庭/工作/社交/宠物称谓、常用问候致谢。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Planner 改 `jieba.lcut` + 模块级单例

**Files:**
- Modify: `sebastian/memory/retrieval.py`（`MemoryRetrievalPlanner` 类 + 新增 `DEFAULT_RETRIEVAL_PLANNER` 单例 + `retrieve_memory_section` 改用单例）
- Create: `tests/unit/memory/test_retrieval_planner_tokenize.py`

- [ ] **Step 1: 写失败测试（分词精度 + 四条 lane 激活）**

`tests/unit/memory/test_retrieval_planner_tokenize.py`:

```python
from __future__ import annotations

import pytest

from sebastian.memory.retrieval import (
    MemoryRetrievalPlanner,
    RetrievalContext,
)


def _ctx(msg: str) -> RetrievalContext:
    return RetrievalContext(
        subject_id="user:eric",
        session_id="s1",
        agent_type="sebastian",
        user_message=msg,
    )


@pytest.mark.parametrize(
    "msg",
    ["我需要一封推荐信", "帮我写推荐信", "这是一封推荐信"],
)
def test_recommendation_letter_does_not_trigger_profile(msg: str) -> None:
    """'推荐信' 作为长词不应被拆出 '推荐' 误触发 Profile Lane。"""
    planner = MemoryRetrievalPlanner()
    plan = planner.plan(_ctx(msg))
    assert plan.profile_lane is False


def test_recommend_verb_triggers_profile() -> None:
    planner = MemoryRetrievalPlanner()
    plan = planner.plan(_ctx("给我推荐一个餐厅"))
    assert plan.profile_lane is True


def test_remember_triggers_episode() -> None:
    planner = MemoryRetrievalPlanner()
    plan = planner.plan(_ctx("你还记得我说过的项目吗"))
    assert plan.episode_lane is True


def test_recent_triggers_context() -> None:
    planner = MemoryRetrievalPlanner()
    plan = planner.plan(_ctx("最近进展怎么样"))
    assert plan.context_lane is True


def test_relation_static_word_triggers_relation() -> None:
    planner = MemoryRetrievalPlanner()
    plan = planner.plan(_ctx("我老婆今天做了饭"))
    assert plan.relation_lane is True


@pytest.mark.parametrize("msg", ["hi", "你好", "thanks", "ok"])
def test_small_talk_short_circuits_all_lanes(msg: str) -> None:
    planner = MemoryRetrievalPlanner()
    plan = planner.plan(_ctx(msg))
    assert plan.profile_lane is False
    assert plan.context_lane is False
    assert plan.episode_lane is False
    assert plan.relation_lane is False


def test_empty_message_no_activation() -> None:
    planner = MemoryRetrievalPlanner()
    plan = planner.plan(_ctx(""))
    assert plan.profile_lane is False
    assert plan.context_lane is False
    assert plan.episode_lane is False
    assert plan.relation_lane is False


def test_default_planner_singleton_is_module_level() -> None:
    """retrieve_memory_section 内部必须用同一实例，否则 bootstrap 状态丢失。"""
    from sebastian.memory.retrieval import DEFAULT_RETRIEVAL_PLANNER

    assert isinstance(DEFAULT_RETRIEVAL_PLANNER, MemoryRetrievalPlanner)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/memory/test_retrieval_planner_tokenize.py -v`
Expected: FAIL —
- 现 planner 默认 `profile_lane=True`，`test_small_talk_short_circuits_all_lanes` 会失败
- 现 substring 匹配 "推荐信" 会命中 "推荐"，`test_recommendation_letter_does_not_trigger_profile` 会失败
- `DEFAULT_RETRIEVAL_PLANNER` 不存在，`test_default_planner_singleton_is_module_level` 会 ImportError

- [ ] **Step 3: 改写 `MemoryRetrievalPlanner.plan()` 用 `jieba.lcut` + set 交集**

编辑 `sebastian/memory/retrieval.py`：

**3a) 删除旧关键词常量**（删除第 14-19 行这 5 个 list）：

```python
# 删除：
PROFILE_LANE_KEYWORDS = [...]
EPISODE_LANE_KEYWORDS = [...]
RELATION_LANE_KEYWORDS = [...]
CONTEXT_LANE_KEYWORDS = [...]
SMALL_TALK_PATTERNS = [...]
```

**3b) 顶部新增 import**：

```python
import jieba

from sebastian.memory.retrieval_lexicon import (
    CONTEXT_LANE_WORDS,
    EPISODE_LANE_WORDS,
    PROFILE_LANE_WORDS,
    RELATION_LANE_STATIC_WORDS,
    SMALL_TALK_WORDS,
)
```

**3c) 重写 `MemoryRetrievalPlanner` 类**（替换原第 105-137 行整体）：

```python
class MemoryRetrievalPlanner:
    """Intent-based lane activator using jieba precise tokenization + set intersection.

    Relation lane's trigger set is dynamic: `bootstrap_entity_triggers()` merges
    all canonical entity names + aliases from EntityRegistry at startup; each
    EntityRegistry.upsert_entity() call invokes `reload_entity_triggers()` to
    keep the cache in sync. See spec §7.6 / §7.7.
    """

    def __init__(self) -> None:
        self._relation_trigger_set: frozenset[str] = RELATION_LANE_STATIC_WORDS

    async def bootstrap_entity_triggers(self, registry: "EntityRegistry") -> None:
        """启动期调用：把 Entity Registry 全量 name/aliases 合并进 relation 触发词。"""
        entity_names = await registry.list_all_names_and_aliases()
        self._relation_trigger_set = RELATION_LANE_STATIC_WORDS | frozenset(entity_names)

    async def reload_entity_triggers(self, registry: "EntityRegistry") -> None:
        """Entity 写入末尾调用，刷新触发词缓存。"""
        await self.bootstrap_entity_triggers(registry)

    def plan(self, context: RetrievalContext) -> RetrievalPlan:
        msg = context.user_message.lower().strip()
        if not msg:
            plan = RetrievalPlan(
                profile_lane=False,
                context_lane=False,
                episode_lane=False,
                relation_lane=False,
            )
        else:
            tokens: set[str] = set(jieba.lcut(msg))

            # Small-talk 短路（短消息 + 问候/致谢词）
            if tokens & SMALL_TALK_WORDS and len(tokens) <= 3:
                plan = RetrievalPlan(
                    profile_lane=False,
                    context_lane=False,
                    episode_lane=False,
                    relation_lane=False,
                )
            else:
                plan = RetrievalPlan(
                    profile_lane=bool(tokens & PROFILE_LANE_WORDS),
                    context_lane=bool(tokens & CONTEXT_LANE_WORDS),
                    episode_lane=bool(tokens & EPISODE_LANE_WORDS),
                    relation_lane=bool(tokens & self._relation_trigger_set),
                )
        trace(
            "retrieval.plan",
            session_id=context.session_id,
            agent_type=context.agent_type,
            subject_id=context.subject_id,
            profile_lane=plan.profile_lane,
            context_lane=plan.context_lane,
            episode_lane=plan.episode_lane,
            relation_lane=plan.relation_lane,
            profile_limit=plan.profile_limit,
            context_limit=plan.context_limit,
            episode_limit=plan.episode_limit,
            relation_limit=plan.relation_limit,
        )
        return plan


# Module-level singleton — gateway bootstrap 写入，retrieve_memory_section 读取
DEFAULT_RETRIEVAL_PLANNER: MemoryRetrievalPlanner = MemoryRetrievalPlanner()
```

**3d) `EntityRegistry` 前向引用**（文件顶部 `if TYPE_CHECKING:` 块内添加）：

```python
if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from sebastian.memory.entity_registry import EntityRegistry
```

**3e) `retrieve_memory_section` 改用单例**（替换第 317 行 `planner = MemoryRetrievalPlanner()`）：

```python
# 原：planner = MemoryRetrievalPlanner()
planner = DEFAULT_RETRIEVAL_PLANNER
plan = planner.plan(context)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/memory/test_retrieval_planner_tokenize.py -v`
Expected: PASS — 9 个测试全绿。

- [ ] **Step 5: 现有 retrieval 测试回归**

Run: `pytest tests/unit/memory/ tests/integration/memory/ -v -x`
Expected: 全绿；若有现有测试依赖 `PROFILE_LANE_KEYWORDS` 等已删常量，更新为 import `retrieval_lexicon` 对应 frozenset。

- [ ] **Step 6: mypy + ruff**

Run: `mypy sebastian/memory/retrieval.py && ruff check sebastian/memory/retrieval.py tests/unit/memory/test_retrieval_planner_tokenize.py && ruff format sebastian/memory/retrieval.py tests/unit/memory/test_retrieval_planner_tokenize.py`
Expected: 0 error, 0 warning。

- [ ] **Step 7: Commit**

```bash
git add sebastian/memory/retrieval.py tests/unit/memory/test_retrieval_planner_tokenize.py
git commit -m "feat(memory): Planner 改用 jieba.lcut 精确分词 + frozenset 交集（B3 主体）

- 删除 5 个 *_LANE_KEYWORDS list 常量，改从 retrieval_lexicon 导入
- plan() 用 jieba.lcut 精确模式分词（避免 '推荐信' 被拆成 '推荐' 误触发）
- 匹配改为 O(1) set & frozenset 交集
- 新增 bootstrap_entity_triggers / reload_entity_triggers 异步方法
- 新增模块级 DEFAULT_RETRIEVAL_PLANNER 单例，retrieve_memory_section 改用
- Small-talk 短路严格要求 len(tokens) <= 3

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 3: `EntityRegistry.list_all_names_and_aliases()` + `upsert_entity` reload 钩子

**Files:**
- Modify: `sebastian/memory/entity_registry.py`
- Create: `tests/unit/memory/test_planner_entity_bootstrap.py`
- Create: `tests/integration/memory/test_entity_registry_reload_hook.py`

- [ ] **Step 1: 写失败测试（Planner bootstrap / reload 单测）**

`tests/unit/memory/test_planner_entity_bootstrap.py`:

```python
from __future__ import annotations

import pytest

from sebastian.memory.retrieval import (
    MemoryRetrievalPlanner,
    RetrievalContext,
)
from sebastian.memory.retrieval_lexicon import RELATION_LANE_STATIC_WORDS


def _ctx(msg: str) -> RetrievalContext:
    return RetrievalContext(
        subject_id="user:eric",
        session_id="s1",
        agent_type="sebastian",
        user_message=msg,
    )


class _FakeRegistry:
    def __init__(self, names: list[str]) -> None:
        self._names = names

    async def list_all_names_and_aliases(self) -> list[str]:
        return list(self._names)


@pytest.mark.asyncio
async def test_bootstrap_merges_entity_names() -> None:
    planner = MemoryRetrievalPlanner()
    registry = _FakeRegistry(["小美", "豆豆"])
    await planner.bootstrap_entity_triggers(registry)  # type: ignore[arg-type]
    assert "小美" in planner._relation_trigger_set
    assert "豆豆" in planner._relation_trigger_set
    # 静态词必须仍在
    assert "老婆" in planner._relation_trigger_set


@pytest.mark.asyncio
async def test_bootstrap_merges_aliases() -> None:
    planner = MemoryRetrievalPlanner()
    # 模拟 list_all_names_and_aliases 返回 canonical + aliases 扁平列表
    registry = _FakeRegistry(["小美", "美美", "小美同学"])
    await planner.bootstrap_entity_triggers(registry)  # type: ignore[arg-type]
    for term in ("小美", "美美", "小美同学"):
        assert term in planner._relation_trigger_set


@pytest.mark.asyncio
async def test_entity_name_activates_relation_lane() -> None:
    planner = MemoryRetrievalPlanner()
    registry = _FakeRegistry(["小美"])
    await planner.bootstrap_entity_triggers(registry)  # type: ignore[arg-type]
    plan = planner.plan(_ctx("小美今天做了饭"))
    assert plan.relation_lane is True


@pytest.mark.asyncio
async def test_alias_activates_relation_lane() -> None:
    planner = MemoryRetrievalPlanner()
    registry = _FakeRegistry(["小美", "美美"])
    await planner.bootstrap_entity_triggers(registry)  # type: ignore[arg-type]
    plan = planner.plan(_ctx("美美来了"))
    assert plan.relation_lane is True


@pytest.mark.asyncio
async def test_reload_reflects_new_entity() -> None:
    planner = MemoryRetrievalPlanner()
    registry = _FakeRegistry(["小美"])
    await planner.bootstrap_entity_triggers(registry)  # type: ignore[arg-type]
    assert "王总" not in planner._relation_trigger_set

    # 模拟新增实体后 reload
    registry._names.append("王总")
    await planner.reload_entity_triggers(registry)  # type: ignore[arg-type]
    assert "王总" in planner._relation_trigger_set
    plan = planner.plan(_ctx("王总来找我"))
    assert plan.relation_lane is True


@pytest.mark.asyncio
async def test_bootstrap_not_called_static_only() -> None:
    planner = MemoryRetrievalPlanner()
    assert planner._relation_trigger_set == RELATION_LANE_STATIC_WORDS
```

- [ ] **Step 2: 写失败测试（EntityRegistry reload 钩子集成测试）**

`tests/integration/memory/test_entity_registry_reload_hook.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from sebastian.memory.entity_registry import EntityRegistry


@pytest.mark.asyncio
async def test_upsert_new_entity_triggers_reload(db_session) -> None:
    planner = AsyncMock()
    registry = EntityRegistry(db_session, planner=planner)
    await registry.upsert_entity(
        canonical_name="王总",
        entity_type="person",
        aliases=["王先生"],
    )
    planner.reload_entity_triggers.assert_awaited_once_with(registry)


@pytest.mark.asyncio
async def test_upsert_existing_entity_merging_aliases_triggers_reload(
    db_session,
) -> None:
    planner = AsyncMock()
    registry = EntityRegistry(db_session, planner=planner)
    await registry.upsert_entity(canonical_name="小美", entity_type="person")
    await registry.upsert_entity(
        canonical_name="小美", entity_type="person", aliases=["美美"]
    )
    assert planner.reload_entity_triggers.await_count == 2


@pytest.mark.asyncio
async def test_none_planner_skips_reload(db_session) -> None:
    registry = EntityRegistry(db_session, planner=None)
    # 不应抛异常
    record = await registry.upsert_entity(
        canonical_name="独行者", entity_type="person"
    )
    assert record.canonical_name == "独行者"


@pytest.mark.asyncio
async def test_list_all_names_and_aliases_flat_order(db_session) -> None:
    registry = EntityRegistry(db_session)
    await registry.upsert_entity(
        canonical_name="小美", entity_type="person", aliases=["美美"]
    )
    await registry.upsert_entity(
        canonical_name="王总", entity_type="person", aliases=[]
    )
    names = await registry.list_all_names_and_aliases()
    assert "小美" in names
    assert "美美" in names
    assert "王总" in names


@pytest.mark.asyncio
async def test_sync_jieba_terms_still_works(db_session, monkeypatch) -> None:
    """重构后 sync_jieba_terms 应复用 list_all_names_and_aliases 行为不变。"""
    from sebastian.memory import entity_registry as er_mod

    captured: list[list[str]] = []

    def _fake_add(terms: list[str]) -> None:
        captured.append(list(terms))

    monkeypatch.setattr(er_mod, "add_entity_terms", _fake_add)

    registry = EntityRegistry(db_session)
    await registry.upsert_entity(
        canonical_name="小美", entity_type="person", aliases=["美美"]
    )
    await registry.sync_jieba_terms()
    assert captured and "小美" in captured[-1] and "美美" in captured[-1]
```

> 说明：`db_session` fixture 已存在于 `tests/integration/conftest.py` 或 `tests/unit/memory/conftest.py`（参考 `tests/unit/memory/test_entity_registry.py`）。若集成测试层缺路径，新建 `tests/integration/memory/conftest.py` 复用相同 fixture。

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/unit/memory/test_planner_entity_bootstrap.py tests/integration/memory/test_entity_registry_reload_hook.py -v`
Expected: FAIL —
- `list_all_names_and_aliases` 不存在 → AttributeError
- `EntityRegistry.__init__` 不接 `planner` kwarg → TypeError

- [ ] **Step 4: 修改 `EntityRegistry`**

编辑 `sebastian/memory/entity_registry.py`：

**4a) `__init__` 加 `planner` 注入**（文件顶部 + 类定义）：

```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import or_, select

from sebastian.memory.segmentation import add_entity_terms
from sebastian.memory.types import MemoryStatus
from sebastian.store.models import EntityRecord, RelationCandidateRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from sebastian.memory.retrieval import MemoryRetrievalPlanner


class EntityRegistry:
    def __init__(
        self,
        db_session: AsyncSession,
        *,
        planner: MemoryRetrievalPlanner | None = None,
    ) -> None:
        self._session = db_session
        self._planner = planner
```

**4b) 新增 `list_all_names_and_aliases()`**（放在 `sync_jieba_terms` 之前）：

```python
    async def list_all_names_and_aliases(self) -> list[str]:
        """Return all canonical_names and aliases as a flat list.

        Shared by sync_jieba_terms() and MemoryRetrievalPlanner
        .bootstrap_entity_triggers(). No deduplication — callers pass through
        frozenset/add_entity_terms which handle dedup naturally.
        """
        result = await self._session.scalars(select(EntityRecord))
        names: list[str] = []
        for record in result.all():
            names.append(record.canonical_name)
            names.extend(record.aliases)
        return names
```

**4c) 重构 `sync_jieba_terms` 复用新方法**：

```python
    async def sync_jieba_terms(self) -> None:
        """Register all entity canonical names and aliases with jieba."""
        terms = await self.list_all_names_and_aliases()
        add_entity_terms(terms)
```

**4d) `upsert_entity` 两个 return 前都挂 reload**：

```python
    async def upsert_entity(
        self,
        canonical_name: str,
        entity_type: str,
        aliases: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EntityRecord:
        result = await self._session.scalars(
            select(EntityRecord).where(EntityRecord.canonical_name == canonical_name)
        )
        existing = result.first()

        now = datetime.now(UTC)

        if existing is not None:
            merged = list({*existing.aliases, *(aliases or [])})
            existing.aliases = merged
            if metadata is not None:
                existing.entity_metadata = metadata
            existing.updated_at = now
            await self._session.flush()
            await self._notify_planner_reload()
            return existing

        record = EntityRecord(
            id=str(uuid4()),
            canonical_name=canonical_name,
            entity_type=entity_type,
            aliases=aliases or [],
            entity_metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )
        self._session.add(record)
        await self._session.flush()
        await self._notify_planner_reload()
        return record

    async def _notify_planner_reload(self) -> None:
        """Trigger planner trigger-set refresh after a write. No-op if unwired."""
        if self._planner is not None:
            await self._planner.reload_entity_triggers(self)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/unit/memory/test_planner_entity_bootstrap.py tests/integration/memory/test_entity_registry_reload_hook.py -v`
Expected: PASS — 10 个测试全绿。

- [ ] **Step 6: 现有 EntityRegistry 测试回归**

Run: `pytest tests/unit/memory/test_entity_registry.py -v`
Expected: PASS — 现有 `test_sync_jieba_terms_calls_add_entity_terms` 等保持绿（`sync_jieba_terms` 行为不变）。

- [ ] **Step 7: mypy + ruff**

Run: `mypy sebastian/memory/entity_registry.py && ruff check sebastian/memory/entity_registry.py tests/unit/memory/test_planner_entity_bootstrap.py tests/integration/memory/test_entity_registry_reload_hook.py && ruff format sebastian/memory/entity_registry.py tests/unit/memory/test_planner_entity_bootstrap.py tests/integration/memory/test_entity_registry_reload_hook.py`
Expected: 0 error, 0 warning。

- [ ] **Step 8: Commit**

```bash
git add sebastian/memory/entity_registry.py tests/unit/memory/test_planner_entity_bootstrap.py tests/integration/memory/test_entity_registry_reload_hook.py
git commit -m "feat(memory): EntityRegistry 加 list_all_names_and_aliases + planner reload 钩子

- 新增 list_all_names_and_aliases()：sync_jieba_terms 与 Planner bootstrap 共用
- 重构 sync_jieba_terms 复用新方法（行为不变）
- __init__ 加可选 planner kwarg
- upsert_entity 两个返回路径末尾调 _notify_planner_reload
- planner=None 时跳过 reload（测试和独立调用用）

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Gateway 启动期 bootstrap Planner 触发词

**Files:**
- Modify: `sebastian/gateway/app.py`（lifespan 启动块，`sync_jieba_terms` 调用之后）
- Modify: 所有 `EntityRegistry(session)` 构造点（写路径）传入 `planner=DEFAULT_RETRIEVAL_PLANNER`
- Create: `tests/integration/test_gateway_planner_bootstrap.py`

- [ ] **Step 1: 盘点 EntityRegistry 构造点（区分读/写路径）**

Run: `rg -n "EntityRegistry\(" sebastian/ --type py`
Expected 列出的每个构造点按路径分类：
- **写路径**（会调 `upsert_entity`，需传 `planner=DEFAULT_RETRIEVAL_PLANNER`）：Consolidator / write pipeline / resolver / 各 Extractor 后处理
- **只读路径**（不调 `upsert_entity`，可不传）：`retrieve_memory_section`（只 `list_relations`）、`snapshot` 调用

把清单写进本 Task 的 PR 描述里。

- [ ] **Step 2: 写失败测试（启动后 Planner 带 Entity 名）**

`tests/integration/test_gateway_planner_bootstrap.py`:

```python
from __future__ import annotations

import pytest

from sebastian.memory.entity_registry import EntityRegistry
from sebastian.memory.retrieval import (
    DEFAULT_RETRIEVAL_PLANNER,
    RetrievalContext,
)
from sebastian.memory.retrieval_lexicon import RELATION_LANE_STATIC_WORDS


@pytest.mark.asyncio
async def test_gateway_startup_bootstraps_planner_entity_triggers(
    db_session_factory,
) -> None:
    # 预置一个实体（模拟历史数据）
    async with db_session_factory() as session:
        await EntityRegistry(session).upsert_entity(
            canonical_name="王总", entity_type="person", aliases=["王先生"]
        )
        await session.commit()

    # 重置 Planner 状态（避免测试污染）
    DEFAULT_RETRIEVAL_PLANNER._relation_trigger_set = RELATION_LANE_STATIC_WORDS

    # 手动触发 bootstrap（与 gateway lifespan 中调用的是同一逻辑）
    async with db_session_factory() as session:
        await DEFAULT_RETRIEVAL_PLANNER.bootstrap_entity_triggers(
            EntityRegistry(session)
        )

    assert "王总" in DEFAULT_RETRIEVAL_PLANNER._relation_trigger_set
    assert "王先生" in DEFAULT_RETRIEVAL_PLANNER._relation_trigger_set
    assert RELATION_LANE_STATIC_WORDS <= DEFAULT_RETRIEVAL_PLANNER._relation_trigger_set

    plan = DEFAULT_RETRIEVAL_PLANNER.plan(
        RetrievalContext(
            subject_id="user:eric",
            session_id="s1",
            agent_type="sebastian",
            user_message="王总来找我",
        )
    )
    assert plan.relation_lane is True
```

> 说明：测试依赖 `db_session_factory` fixture（参考 `tests/integration/test_gateway_startup.py`）。测试**不启真实 gateway**，直接调 bootstrap（与 lifespan 执行等价逻辑）。

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/integration/test_gateway_planner_bootstrap.py -v`
Expected: 视 db_session 准备状态，可能因 bootstrap 未调而 relation 词集少王总 → FAIL。

- [ ] **Step 4: 在 `gateway/app.py` lifespan 里加 bootstrap 调用**

编辑 `sebastian/gateway/app.py:85-92`（现有 `sync_jieba_terms` 调用块）：

```python
    async with db_factory() as _seed_session:
        await seed_builtin_slots(_seed_session)
        try:
            _entity_registry = EntityRegistry(_seed_session)
            await _entity_registry.sync_jieba_terms()
            # 新增：把 Entity 名灌入 Planner relation 触发词缓存
            from sebastian.memory.retrieval import DEFAULT_RETRIEVAL_PLANNER

            await DEFAULT_RETRIEVAL_PLANNER.bootstrap_entity_triggers(_entity_registry)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "memory bootstrap (jieba + planner) failed at startup: %s", exc
            )
```

> 两个 bootstrap 共用同一 `_entity_registry` 实例 + 同一 session，避免双 round-trip。

- [ ] **Step 5: 写路径注入 planner**

对 Step 1 盘点出的每个**写路径** `EntityRegistry(session)` 构造点，改为：

```python
from sebastian.memory.retrieval import DEFAULT_RETRIEVAL_PLANNER

registry = EntityRegistry(session, planner=DEFAULT_RETRIEVAL_PLANNER)
```

只读路径保持不传（`None` 跳过 reload，不影响行为）。

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest tests/integration/test_gateway_planner_bootstrap.py -v`
Expected: PASS。

- [ ] **Step 7: 全量回归**

Run: `pytest tests/ -x`
Expected: 全绿。若有测试互相污染 Planner 单例状态，在 `tests/unit/memory/conftest.py` 加 autouse fixture：

```python
import pytest

from sebastian.memory.retrieval import DEFAULT_RETRIEVAL_PLANNER
from sebastian.memory.retrieval_lexicon import RELATION_LANE_STATIC_WORDS


@pytest.fixture(autouse=True)
def _reset_default_planner() -> None:
    DEFAULT_RETRIEVAL_PLANNER._relation_trigger_set = RELATION_LANE_STATIC_WORDS
    yield
    DEFAULT_RETRIEVAL_PLANNER._relation_trigger_set = RELATION_LANE_STATIC_WORDS
```

- [ ] **Step 8: mypy + ruff**

Run: `mypy sebastian/gateway/app.py sebastian/memory/ && ruff check sebastian/ tests/ && ruff format sebastian/ tests/`
Expected: 0 error, 0 warning。

- [ ] **Step 9: Commit**

```bash
git add sebastian/gateway/app.py tests/integration/test_gateway_planner_bootstrap.py
# 加上所有写路径改造的文件
git commit -m "feat(memory): gateway 启动期 bootstrap Planner relation 触发词

- lifespan 里 EntityRegistry 实例复用：sync_jieba_terms + bootstrap_entity_triggers
- 写路径 EntityRegistry 构造传入 DEFAULT_RETRIEVAL_PLANNER（upsert 后自动 reload）
- 只读路径维持 planner=None 跳过 reload

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---


## Task 5: B2 — 拆 `MIN_CONFIDENCE` 成双阈值

**Files:**
- Modify: `sebastian/memory/retrieval.py`（删 `MIN_CONFIDENCE`；加 `MIN_CONFIDENCE_HARD` / `MIN_CONFIDENCE_AUTO_INJECT`；调整 `_keep_record` 与 `MemorySectionAssembler._keep` 默认阈值职责）
- Modify: `tests/unit/memory/test_retrieval_filter.py`（扩展双阈值用例）

> 本 Task 与 Task 1/2/3/4 无代码冲突，可与 B3 链并行。

- [ ] **Step 1: 写失败测试（双阈值过滤矩阵）**

在 `tests/unit/memory/test_retrieval_filter.py` 末尾追加（若文件不存在则新建，复用现有 fixture）：

```python
from __future__ import annotations

from types import SimpleNamespace

from sebastian.memory.retrieval import (
    MIN_CONFIDENCE_AUTO_INJECT,
    MIN_CONFIDENCE_HARD,
    MemorySectionAssembler,
    RetrievalContext,
    RetrievalPlan,
    _keep_record,
)


def _rec(confidence: float) -> SimpleNamespace:
    return SimpleNamespace(
        content="x",
        kind="fact",
        confidence=confidence,
        policy_tags=[],
        status="active",
        valid_until=None,
        valid_from=None,
        subject_id="user:eric",
    )


def _ctx(purpose: str) -> RetrievalContext:
    return RetrievalContext(
        subject_id="user:eric",
        session_id="s1",
        agent_type="sebastian",
        user_message="dummy",
        access_purpose=purpose,
    )


def test_min_confidence_hard_is_0_3() -> None:
    assert MIN_CONFIDENCE_HARD == 0.3


def test_min_confidence_auto_inject_is_0_5() -> None:
    assert MIN_CONFIDENCE_AUTO_INJECT == 0.5


def test_hard_gate_drops_below_0_3_context_injection() -> None:
    assert _keep_record(_rec(0.25), context=_ctx("context_injection")) is False


def test_hard_gate_drops_below_0_3_tool_search() -> None:
    assert _keep_record(_rec(0.25), context=_ctx("tool_search")) is False


def test_hard_gate_passes_at_0_3() -> None:
    assert _keep_record(_rec(0.3), context=_ctx("tool_search")) is True


def test_auto_inject_drops_mid_band() -> None:
    plan = RetrievalPlan()
    out = MemorySectionAssembler().assemble(
        profile_records=[_rec(0.35)],
        context_records=[],
        episode_records=[],
        relation_records=[],
        plan=plan,
        context=_ctx("context_injection"),
    )
    assert out == ""


def test_tool_search_keeps_mid_band() -> None:
    plan = RetrievalPlan()
    out = MemorySectionAssembler().assemble(
        profile_records=[_rec(0.35)],
        context_records=[],
        episode_records=[],
        relation_records=[],
        plan=plan,
        context=_ctx("tool_search"),
    )
    assert "x" in out


def test_auto_inject_keeps_above_gate() -> None:
    plan = RetrievalPlan()
    out = MemorySectionAssembler().assemble(
        profile_records=[_rec(0.55)],
        context_records=[],
        episode_records=[],
        relation_records=[],
        plan=plan,
        context=_ctx("context_injection"),
    )
    assert "x" in out


def test_min_confidence_constant_fully_removed() -> None:
    """旧常量必须彻底删除，避免调用方误用。"""
    import sebastian.memory.retrieval as ret_mod

    assert not hasattr(ret_mod, "MIN_CONFIDENCE")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/memory/test_retrieval_filter.py -v`
Expected: FAIL — `MIN_CONFIDENCE_HARD` / `MIN_CONFIDENCE_AUTO_INJECT` 不存在 → ImportError；`MIN_CONFIDENCE` 还在 → `test_min_confidence_constant_fully_removed` fail。

- [ ] **Step 3: 改 `sebastian/memory/retrieval.py`**

**3a) 删除旧常量**（第 22 行）：

```python
# 删除：
# MIN_CONFIDENCE = 0.3
```

**3b) 新增两个常量**（原位置替换）：

```python
# 硬过滤线：任何路径丢 confidence < 0.3 的记录（spec §6 / artifact-model.md §9.3）
MIN_CONFIDENCE_HARD: float = 0.3

# 自动注入门槛：仅 context_injection 路径额外要求 confidence >= 0.5
MIN_CONFIDENCE_AUTO_INJECT: float = 0.5
```

**3c) `_keep_record` 默认阈值改硬线**（第 29 行）：

```python
def _keep_record(
    record: Any,
    *,
    context: RetrievalContext,
    min_confidence: float = MIN_CONFIDENCE_HARD,
) -> bool:
```

**3d) `MemorySectionAssembler.assemble` 默认阈值改硬线、内嵌 `_keep` 加注入门槛**（第 150-200 行）：

```python
class MemorySectionAssembler:
    def assemble(
        self,
        *,
        profile_records: list[Any],
        context_records: list[Any],
        episode_records: list[Any],
        relation_records: list[Any],
        plan: RetrievalPlan,
        context: RetrievalContext | None = None,
        min_confidence: float = MIN_CONFIDENCE_HARD,
    ) -> str:
        # ... 现有 preamble 不变 ...

        def _keep(record: Any) -> bool:
            policy_tags = getattr(record, "policy_tags", None) or []
            if (
                effective_context.access_purpose == "context_injection"
                and DO_NOT_AUTO_INJECT_TAG in policy_tags
            ):
                filter_counts["do_not_auto_inject"] += 1
                return False
            for tag in policy_tags:
                if tag.startswith("access:"):
                    _, allowed_purpose = tag.split(":", 1)
                    if allowed_purpose != effective_context.access_purpose:
                        filter_counts["access_policy"] += 1
                        return False
                if tag.startswith("agent:"):
                    _, allowed_agent = tag.split(":", 1)
                    if allowed_agent != effective_context.agent_type:
                        filter_counts["agent_policy"] += 1
                        return False

            confidence = getattr(record, "confidence", 1.0)

            # 硬线（任何路径都丢）
            if confidence is not None and confidence < min_confidence:
                filter_counts["confidence"] += 1
                return False

            # 自动注入门槛（仅 context_injection 应用）
            if (
                effective_context.access_purpose == "context_injection"
                and confidence is not None
                and confidence < MIN_CONFIDENCE_AUTO_INJECT
            ):
                filter_counts["confidence"] += 1
                return False

            valid_until = getattr(record, "valid_until", None)
            if valid_until is not None:
                if valid_until.tzinfo is None:
                    valid_until = valid_until.replace(tzinfo=UTC)
                if valid_until <= now:
                    filter_counts["valid_until"] += 1
                    return False

            status = getattr(record, "status", None)
            if status is not None and status != "active":
                return False

            record_subject = getattr(record, "subject_id", None)
            if (
                record_subject is not None
                and effective_context.subject_id
                and record_subject != effective_context.subject_id
            ):
                return False

            valid_from = getattr(record, "valid_from", None)
            if valid_from is not None:
                if valid_from.tzinfo is None:
                    valid_from = valid_from.replace(tzinfo=UTC)
                if valid_from > now:
                    filter_counts["valid_from"] += 1
                    return False

            return True
```

> 注：硬线判断仍保留在 `_keep` 内（不删除）——`_keep_record` 与 `_keep` 是两处独立调用点（前者在工具路径、后者在 assemble 路径），必须各自有硬线。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/memory/test_retrieval_filter.py -v`
Expected: PASS — 9 个测试全绿。

- [ ] **Step 5: `MIN_CONFIDENCE` 残留扫描**

Run: `rg "MIN_CONFIDENCE\b" sebastian/ tests/`
Expected: 无结果（除本 Task 新增的 `MIN_CONFIDENCE_HARD` / `MIN_CONFIDENCE_AUTO_INJECT` 外）。若有旧引用（如 import `MIN_CONFIDENCE`），改为对应新常量。

- [ ] **Step 6: 全量回归 + lint**

Run: `pytest tests/unit/memory/ tests/integration/memory/ -v`
Expected: 全绿。

Run: `mypy sebastian/memory/retrieval.py && ruff check sebastian/memory/retrieval.py tests/unit/memory/test_retrieval_filter.py && ruff format sebastian/memory/retrieval.py tests/unit/memory/test_retrieval_filter.py`
Expected: 0 error, 0 warning。

- [ ] **Step 7: Commit**

```bash
git add sebastian/memory/retrieval.py tests/unit/memory/test_retrieval_filter.py
git commit -m "feat(memory): confidence 阈值拆成硬线 0.3 + 自动注入门槛 0.5（B2）

- 删除 MIN_CONFIDENCE 单阈值常量
- 新增 MIN_CONFIDENCE_HARD=0.3（所有路径共用）
- 新增 MIN_CONFIDENCE_AUTO_INJECT=0.5（仅 context_injection）
- _keep_record 默认用硬线
- MemorySectionAssembler._keep 内先硬线后注入门槛
- tool_search 路径现在能拿到 [0.3, 0.5) 的中间带记录

对应 retrieval.md §7.3 / artifact-model.md §9.3。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 6: B1 — `_memory_section()` depth 守卫（fail-closed）

**Files:**
- Modify: `sebastian/core/base_agent.py:236-245`（`_memory_section` 顶部）
- Create: `tests/unit/memory/test_memory_section_depth_guard.py`

> 本 Task 独立，可与 Task 1/2/3/4/5 并行。

- [ ] **Step 1: 写失败测试**

`tests/unit/memory/test_memory_section_depth_guard.py`:

```python
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_depth_1_injects_memory(base_agent_with_memory) -> None:
    """depth=1 应走进正常注入逻辑，返回带记忆内容的字符串（fixture 预置一条 profile 记录）。"""
    agent = base_agent_with_memory
    agent._current_depth["s1"] = 1
    out = await agent._memory_section(
        session_id="s1", agent_context="sebastian", user_message="我喜欢茶"
    )
    assert "Current facts about user" in out or out != ""


@pytest.mark.asyncio
async def test_depth_2_returns_empty(base_agent_with_memory) -> None:
    agent = base_agent_with_memory
    agent._current_depth["s1"] = 2
    out = await agent._memory_section(
        session_id="s1", agent_context="worker", user_message="我喜欢茶"
    )
    assert out == ""


@pytest.mark.asyncio
async def test_depth_missing_returns_empty(base_agent_with_memory) -> None:
    agent = base_agent_with_memory
    agent._current_depth.pop("s1", None)
    out = await agent._memory_section(
        session_id="s1", agent_context="sebastian", user_message="我喜欢茶"
    )
    assert out == ""


@pytest.mark.asyncio
async def test_depth_zero_returns_empty(base_agent_with_memory) -> None:
    agent = base_agent_with_memory
    agent._current_depth["s1"] = 0
    out = await agent._memory_section(
        session_id="s1", agent_context="sebastian", user_message="我喜欢茶"
    )
    assert out == ""
```

**Fixture 设计**（放在同文件顶部或 `tests/unit/memory/conftest.py` 扩展）：

```python
import pytest

from sebastian.core.base_agent import BaseAgent


@pytest.fixture
async def base_agent_with_memory(db_session_factory, monkeypatch):
    """最小化 BaseAgent 实例，确保 _memory_section 能返回非空字符串。

    - memory_settings.enabled=True
    - db_factory 指向测试库
    - 预置一条高 confidence profile 记录（让 depth=1 路径拿到真实内容）
    """
    import sebastian.gateway.state as state
    from sebastian.gateway.state import MemoryRuntimeSettings
    from sebastian.memory.profile_store import ProfileMemoryStore

    state.memory_settings = MemoryRuntimeSettings(enabled=True)

    async with db_session_factory() as session:
        store = ProfileMemoryStore(session)
        await store.insert_record(
            subject_id="user:eric",
            kind="fact",
            content="喜欢茶",
            slot_id=None,
            cardinality=None,
            resolution_policy=None,
            confidence=0.9,
            source="explicit",
        )
        await session.commit()

    class _TestAgent(BaseAgent):
        pass

    agent = _TestAgent(
        agent_type="sebastian",
        db_factory=db_session_factory,
        # 其他参数补齐到 BaseAgent 当前 __init__ 签名最小必需
    )
    return agent
```

> 说明：`ProfileMemoryStore.insert_record` 签名需核对现 API；如命名不同，按实际调整。`BaseAgent.__init__` 必需参数按当前源码补齐（可能需 `llm`、`tools` 等 mock）。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/memory/test_memory_section_depth_guard.py -v`
Expected: FAIL —
- `test_depth_2_returns_empty`：当前无守卫，depth=2 也返回非空 → fail
- `test_depth_missing_returns_empty`：同上
- `test_depth_zero_returns_empty`：同上

- [ ] **Step 3: 在 `_memory_section()` 顶部加 depth 守卫**

编辑 `sebastian/core/base_agent.py:236-245`：

```python
    async def _memory_section(
        self,
        session_id: str,
        agent_context: str,
        user_message: str,
    ) -> str:
        """Return assembled memory context string. Empty string on any failure or if disabled.

        depth 守卫（spec §5 / artifact-model.md §10.4）：长期记忆只注入给 depth=1
        的 Sebastian 本体。depth != 1（包括未初始化 → None）一律 fail-closed 返回 "".
        """
        depth = self._current_depth.get(session_id)
        if depth != 1:
            return ""

        if self._db_factory is None:
            return ""
        # ... 原有逻辑不变 ...
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/memory/test_memory_section_depth_guard.py -v`
Expected: PASS — 4 个测试全绿。

- [ ] **Step 5: `depth=1` happy-path 回归测试**

Run: `pytest tests/unit/memory/test_memory_section_depth_guard.py::test_depth_1_injects_memory tests/ -k memory -v`
Expected: PASS；确认 depth=1 的注入链路没被误伤。

- [ ] **Step 6: mypy + ruff**

Run: `mypy sebastian/core/base_agent.py && ruff check sebastian/core/base_agent.py tests/unit/memory/test_memory_section_depth_guard.py && ruff format sebastian/core/base_agent.py tests/unit/memory/test_memory_section_depth_guard.py`
Expected: 0 error, 0 warning。

- [ ] **Step 7: Commit**

```bash
git add sebastian/core/base_agent.py tests/unit/memory/test_memory_section_depth_guard.py
git commit -m "fix(memory): _memory_section 加 depth 守卫（fail-closed，仅 depth=1 注入）

- depth != 1（含 None / 0 / 子 agent）一律返回空字符串
- 对应 artifact-model.md §10.4：长期记忆只给 Sebastian 本体
- 消除子 agent 泄露主人记忆的通道
- scope 严格限定记忆注入；ToolCallContext.depth 默认值本 spec 不改

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 7: Pinned 字样清理 + `retrieval.md §7.4` 状态更新

**Files:**
- Modify: `sebastian/memory/prompts.py:152`
- Modify: `docs/superpowers/specs/2026-04-20-dynamic-slot-system-design.md:518`
- Modify: `docs/superpowers/plans/2026-04-20-dynamic-slot-system.md:1422`
- Modify: `docs/architecture/spec/memory/retrieval.md §7.4`
- Create: `tests/unit/memory/test_prompts.py`（或扩展已有）

> 本 Task 与其他 Task 无代码冲突，可放最后也可并行。

- [ ] **Step 1: 写失败测试（Extractor prompt 不含 pinned 引导）**

`tests/unit/memory/test_prompts.py`:

```python
from __future__ import annotations


def test_extractor_prompt_no_pinned_example() -> None:
    """spec §10.2：Extractor LLM 不得提议 pinned，prompt 中不应出现诱导字样。"""
    from sebastian.memory import prompts

    # 渲染 Extractor 用户/系统 prompt（按实际模块 API 调整）
    text = prompts.EXTRACTOR_SCHEMA_PROMPT if hasattr(
        prompts, "EXTRACTOR_SCHEMA_PROMPT"
    ) else open(prompts.__file__, encoding="utf-8").read()

    # 大小写不敏感匹配
    assert "pinned" not in text.lower(), (
        "Extractor prompt 仍含 'pinned' 字样，违反 artifact-model.md §10.2"
    )
```

> 说明：`prompts.py` 是 Markdown 文本常量文件；若当前模块以字符串常量形式对外暴露（如 `EXTRACTOR_SCHEMA_PROMPT`），优先用常量；否则退回读原文件（稳健）。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/memory/test_prompts.py -v`
Expected: FAIL — `prompts.py:152` 含 `"pinned" 表示钉住`。

- [ ] **Step 3: 改 `sebastian/memory/prompts.py:152`**

```markdown
| policy_tags | array<string> | 一般 []，不要主动设置任何值 |
```

（替换原 `| policy_tags | array<string> | 一般 []；"pinned" 表示钉住 |`）

- [ ] **Step 4: 同步改文档 pinned 字样**

`docs/superpowers/specs/2026-04-20-dynamic-slot-system-design.md:518` 同样把 `"pinned" 表示钉住` 改为 `不要主动设置任何值`。

`docs/superpowers/plans/2026-04-20-dynamic-slot-system.md:1422` 同样改。

- [ ] **Step 5: 更新 `docs/architecture/spec/memory/retrieval.md §7.4` 实现状态段**

把原 "实现状态：`pinned` 豁免逻辑当前尚未在 `MemorySectionAssembler` 中实现，为**待补功能**。实现时应在 assembler 中先单独收集..." 替换为：

```markdown
**实现状态**：`pinned` 豁免逻辑为**独立未来 spec** 范围，当前 Retrieval Fixes spec（[docs/superpowers/specs/2026-04-20-memory-retrieval-fixes-design.md](../../../superpowers/specs/2026-04-20-memory-retrieval-fixes-design.md)）明确**不实现**。任何 pinned 相关代码改动必须等独立 spec 批准；原因与触发条件见该 spec §13.1。
```

> 相对路径按 `docs/architecture/spec/memory/retrieval.md` 所在层级向上回 3 级到 `docs/` 根；如有偏差按实际调整。

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest tests/unit/memory/test_prompts.py -v`
Expected: PASS。

- [ ] **Step 7: 全局 `pinned` 残留扫描**

Run: `rg -n "pinned" sebastian/ tests/`
Expected: 
- `sebastian/memory/artifact.py` / `store` / 类型定义里如仍有 `policy_tags` 字段定义（不含 "pinned 表示" 字样）可保留——这是未来使用入口
- 若有**代码逻辑**（`if "pinned" in policy_tags:` 之类分支），这是 dead code，删除

同时手动 `rg "pinned" docs/`，确认除 §13.1 声明和 `artifact-model.md §10.1-§10.3`（设计档案，保留）外无其他诱导性描述。

- [ ] **Step 8: mypy + ruff**

Run: `mypy sebastian/memory/prompts.py && ruff check sebastian/memory/prompts.py tests/unit/memory/test_prompts.py && ruff format sebastian/memory/prompts.py tests/unit/memory/test_prompts.py`
Expected: 0 error, 0 warning。

- [ ] **Step 9: Commit**

```bash
git add sebastian/memory/prompts.py tests/unit/memory/test_prompts.py \
        docs/superpowers/specs/2026-04-20-dynamic-slot-system-design.md \
        docs/superpowers/plans/2026-04-20-dynamic-slot-system.md \
        docs/architecture/spec/memory/retrieval.md
git commit -m "chore(memory): 清理 Extractor prompt 与 spec 里诱导 pinned 的字样

- prompts.py:152 'pinned 表示钉住' → '不要主动设置任何值'（spec §10.2 禁止 LLM 设）
- dynamic-slot-system spec / plan 同步调整措辞
- retrieval.md §7.4 实现状态从'待补'改为'独立 spec 前不实现'
- 新增 test_prompts.py 守护：Extractor prompt 不含 pinned 字样

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## 验收 Checklist（对齐 spec §11）

完成所有 Task 后逐项勾选：

- [ ] 1. `depth != 1` 的子 agent `_memory_section()` 返回 `""` — Task 6 单测覆盖
- [ ] 2. `depth` 未初始化（None）时返回 `""` — Task 6 单测覆盖
- [ ] 3. `context_injection` 路径丢弃 confidence ∈ [0.3, 0.5) — Task 5 单测覆盖
- [ ] 4. `tool_search` 路径返回 confidence ∈ [0.3, 0.5) — Task 5 单测覆盖
- [ ] 5. 任何路径丢弃 confidence < 0.3 — Task 5 单测覆盖
- [ ] 6. "推荐信" 类长词不触发 Profile Lane 误判 — Task 2 单测覆盖
- [ ] 7. Entity Registry 里用户私有名字命中 Relation Lane — Task 3 单测覆盖
- [ ] 8. Entity 新增 / 合并 aliases 后下一轮对话立即生效 — Task 3 集成测试覆盖
- [ ] 9. Extractor LLM prompt 不含 `"pinned"` — Task 7 单测覆盖
- [ ] 10. `rg "MIN_CONFIDENCE\b" sebastian/` 仅返回 `MIN_CONFIDENCE_HARD` / `MIN_CONFIDENCE_AUTO_INJECT`
- [ ] 11. `pytest tests/` 全绿（无回归）
- [ ] 12. `mypy sebastian/` 0 error；`ruff check sebastian/ tests/` 0 warning
- [ ] 13. `docs/architecture/spec/memory/retrieval.md §7.4` 状态段已改为"不实现"措辞

全部打勾后在 feature branch 上开 PR，标题：`fix(memory): Retrieval 路径三项修复（depth / confidence 双阈值 / Planner 词库）`，base = `main`，合并方式 squash。

---

## 自查备忘

- 每个 Task 执行后先跑**本 Task 单测**再跑**全量回归**，避免污染定位
- Planner 单例状态在跨 Task 测试之间通过 `conftest.py` autouse fixture 重置（Task 4 Step 7）
- 任何 `rg "pinned"` 的代码分支发现都按 Task 7 Step 7 删除，不要"顺手补"成豁免实现
- Task 4 的写路径 EntityRegistry 盘点结果放 PR 描述，review 时核对
