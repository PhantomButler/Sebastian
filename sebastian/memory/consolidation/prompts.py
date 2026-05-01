from __future__ import annotations

import json
from collections.abc import Iterable

from sebastian.memory.types import SlotDefinition


def group_slots_by_kind(slots: Iterable[SlotDefinition]) -> dict[str, list[dict[str, str]]]:
    """按 kind_constraints 把 slot 分桶。一个 slot 含多个 kind 时复制到所有桶。"""
    grouped: dict[str, list[dict[str, str]]] = {}
    for s in slots:
        entry = {
            "slot_id": s.slot_id,
            "cardinality": s.cardinality.value,
            "resolution_policy": s.resolution_policy.value,
            "description": s.description,
        }
        for kind in s.kind_constraints:
            grouped.setdefault(kind.value, []).append(entry)
    return grouped


_EXAMPLE_1_JSON = """\
{
  "artifacts": [
    {
      "kind": "preference",
      "content": "用户喜欢看《三体》",
      "structured_payload": {"title": "三体"},
      "subject_hint": null,
      "scope": "user",
      "slot_id": "user.profile.like_book",
      "cardinality": null,
      "resolution_policy": null,
      "confidence": 0.95,
      "source": "explicit",
      "evidence": [{"quote": "我喜欢看三体"}],
      "valid_from": null,
      "valid_until": null,
      "policy_tags": [],
      "needs_review": false
    }
  ],
  "proposed_slots": []
}"""

_EXAMPLE_2_JSON = """\
{
  "artifacts": [
    {
      "kind": "fact",
      "content": "用户居住在上海浦东",
      "structured_payload": {"city": "上海", "district": "浦东"},
      "subject_hint": null,
      "scope": "user",
      "slot_id": "user.profile.location",
      "cardinality": "single",
      "resolution_policy": "supersede",
      "confidence": 0.9,
      "source": "explicit",
      "evidence": [{"quote": "我住在上海浦东"}],
      "valid_from": null,
      "valid_until": null,
      "policy_tags": [],
      "needs_review": false
    }
  ],
  "proposed_slots": [
    {
      "slot_id": "user.profile.location",
      "scope": "user",
      "subject_kind": "user",
      "cardinality": "single",
      "resolution_policy": "supersede",
      "kind_constraints": ["fact"],
      "description": "用户居住地"
    }
  ]
}"""

_EXAMPLE_3_JSON = """{"artifacts": [], "proposed_slots": []}"""


def build_slot_rules_section(known_slots_by_kind: dict[str, list[dict[str, str]]]) -> str:
    slots_block = json.dumps(known_slots_by_kind, ensure_ascii=False, indent=2)
    return f"""\
# 已注册 Slot（按 kind 分组）

```json
{slots_block}
```

# Slot 选择规则

1. 只有 kind=fact 和 kind=preference 必须 slot_id 非 null；其余 kind 可 slot_id=null。
2. 优先复用 known_slots 中语义匹配的 slot，description 相近即可复用。
3. 确实找不到才进 proposed_slots 数组。artifact.slot_id 必须和 proposed_slots[i].slot_id 一致。
4. 提议的 slot_id 禁止与 known_slots 中任何已存在重名。

# Cardinality / Resolution Policy 参照表

| 语义模式 | cardinality | resolution_policy | 举例 |
|---|---|---|---|
| 唯一属性（姓名 / 时区 / 当前焦点） | single | supersede | user.profile.name |
| 可枚举偏好（喜欢的书 / 音乐） | multi | append_only | user.profile.like_book |
| 可合并集合（擅长领域 / 技能列表） | multi | merge | user.profile.skill |
| 时效性状态（本周安排 / 季度目标） | single | time_bound | user.goal.current_quarter |
| 行为 / 事件流 | multi | append_only | user.behavior.login_event |

禁止组合：cardinality=single + resolution_policy=append_only。

# 示例

## 示例 1：复用已有 slot
{_EXAMPLE_1_JSON}

## 示例 2：提议新 slot + 同一轮落 artifact
{_EXAMPLE_2_JSON}

## 示例 3：无可提取内容
{_EXAMPLE_3_JSON}
"""


_EXTRACTOR_FIELD_TABLE = """\
# 输出契约

响应必须是纯 JSON，不能有解释文字 / Markdown 围栏 / 代码块。顶层结构：

{"artifacts": [ CandidateArtifact, ... ], "proposed_slots": [ ProposedSlot, ... ]}

两个数组允许为空 []。

## CandidateArtifact 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| kind | enum | fact / preference / episode / summary / entity / relation |
| content | string | 自然语言描述，≤ 200 字 |
| structured_payload | object | 结构化载荷；无则 {} |
| subject_hint | string \\| null | 一般 null |
| scope | enum | user / session / project / agent |
| slot_id | string \\| null | 见 Slot 选择规则 |
| cardinality | enum \\| null | single / multi / null |
| resolution_policy | enum \\| null | supersede / merge / append_only / time_bound / null |
| confidence | float | 0.0 ~ 1.0 |
| source | enum | explicit / inferred / observed |
| evidence | array | [{"quote": "..."}] |
| valid_from | ISO-8601 \\| null | 一般 null |
| valid_until | ISO-8601 \\| null | 一般 null |
| policy_tags | array<string> | 一般 []，不要主动设置任何值 |
| needs_review | bool | 不确定时 true |

## ProposedSlot 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| slot_id | string | 三段式 {scope}.{category}.{attribute}，≤ 64 |
| scope | enum | 与 slot_id 首段一致 |
| subject_kind | string | user / project / agent |
| cardinality | enum | single / multi |
| resolution_policy | enum | supersede / merge / append_only / time_bound |
| kind_constraints | array<enum> | 至少 1 项 |
| description | string | 中文，≤ 40 字 |
"""


_CONFIDENCE_SCORING_GUIDE = """\
## 置信度评分指南

confidence 字段反映你对该记忆内容准确性的把握程度：

| 分值区间 | 适用场景 |
|---|---|
| 0.9 – 1.0 | 用户明确陈述的事实（"我喜欢X"、"我叫X"、"我在X工作"） |
| 0.7 – 0.9 | 对话中直接体现但非明确声明（"每次都选X"、重复提及同一偏好） |
| 0.5 – 0.7 | 从行为或上下文推断的偏好，有一定根据但非直述 |
| 0.3 – 0.5 | 模糊线索或单次偶然提及，可信度较低 |
| < 0.3 | 高度不确定的推断，几乎只有间接证据（建议不提取） |

附加约束：
- source=explicit 时，confidence 不应低于 0.9
- source=inferred 时，confidence 不应超过 0.75
- 宁可少提取，不提取低质量记忆
"""


def build_extractor_prompt(known_slots_by_kind: dict[str, list[dict[str, str]]]) -> str:
    rules = build_slot_rules_section(known_slots_by_kind)
    return f"""\
你是记忆提取助手。分析给定的对话内容，抽取出有记忆价值的信息。

{_EXTRACTOR_FIELD_TABLE}

{_CONFIDENCE_SCORING_GUIDE}

{rules}
"""


def build_consolidator_prompt(known_slots_by_kind: dict[str, list[dict[str, str]]]) -> str:
    base = build_extractor_prompt(known_slots_by_kind)
    addendum = """\

# Consolidator 额外任务

除了抽取 artifacts 和 proposed_slots，你还需要：

1. summaries: 对整个会话生成 1 条中文摘要（≤ 300 字），加入输出 JSON
2. proposed_actions: 对与新信息冲突的既有 artifact 提出 EXPIRE 动作

完整输出 schema：
{
  "artifacts": [...],
  "proposed_slots": [...],
  "summaries": [{"content": "...", "scope": "session"}],
  "proposed_actions": [{"action": "EXPIRE", "memory_id": "...", "reason": "..."}]
}
"""
    return base + addendum
