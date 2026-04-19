# memory

> 上级索引：[sebastian/](../README.md)

## 模块职责

提供 Agent 记忆系统的基础设施：

- **工作记忆**：`WorkingMemory`，进程内、任务作用域的临时状态。
- **会话历史兼容层**：`EpisodicMemory`，基于 `SessionStore` 读写当前 session 的消息历史，用于兼容现有对话上下文链路；它不是新的 Episode Store。
- **统一入口**：`MemoryStore`，当前聚合 working + session history compatibility layer。
- **Phase A 长期记忆基础设施**：记忆 artifact 类型、slot 注册表、FTS 分词辅助、决策日志写入器。

真正的 `ProfileMemoryStore`（画像存储）和 `EpisodeMemoryStore`（经历存储）尚未实现，将在 Phase B 落地。当前已有对应 ORM 记录定义在 `sebastian/store/models.py`，包括 `MemorySlotRecord`、`ProfileMemoryRecord`、`EpisodeMemoryRecord`、`EntityRecord`、`RelationCandidateRecord`、`MemoryDecisionLogRecord`。

语义记忆（向量检索）为后续规划能力，当前未实现。

## 目录结构

```
memory/
├── __init__.py           # 空，包入口
├── decision_log.py       # MemoryDecisionLogger：把 ResolveDecision 写入 memory_decision_log
├── episodic_memory.py    # EpisodicMemory：会话历史兼容层，底层依赖 SessionStore，不是新 Episode Store
├── segmentation.py       # jieba FTS 分词辅助：索引分词、查询分词、实体词注入
├── slots.py              # SlotRegistry + 6 个内置 SlotDefinition + DEFAULT_SLOT_REGISTRY
├── store.py              # MemoryStore：统一聚合 working + 会话历史兼容层
├── types.py              # 记忆系统 Pydantic models 与 StrEnum 类型
└── working_memory.py     # WorkingMemory：进程内 dict，按 task_id 隔离，任务结束后清除
```

## Phase A 基础文件

| 文件 | 当前职责 |
|------|----------|
| [types.py](types.py) | 定义长期记忆基础类型：`MemoryKind`、`MemoryScope`、`MemoryStatus`、`MemorySource`、`MemoryDecisionType`、`Cardinality`、`ResolutionPolicy`、`SlotDefinition`、`CandidateArtifact`、`MemoryArtifact`、`ResolveDecision` |
| [slots.py](slots.py) | 提供 `SlotRegistry`、6 个内置 `SlotDefinition` 和 `DEFAULT_SLOT_REGISTRY`；当前校验 `fact` / `preference` 必须绑定已注册 slot |
| [segmentation.py](segmentation.py) | 提供基于 `jieba.cut_for_search()` 的 FTS5 中文分词辅助：`segment_for_fts()`、`terms_for_query()`、`add_entity_terms()` |
| [decision_log.py](decision_log.py) | 提供 `MemoryDecisionLogger.append()`，把 `ResolveDecision` 写入 `MemoryDecisionLogRecord` |

> Phase B 占位：`ProfileMemoryStore` 和 `EpisodeMemoryStore` 尚未实现。不要把现有 [episodic_memory.py](episodic_memory.py) 当作新的 Episode Store 扩展；它只负责现有 session 消息历史兼容。

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 任务临时状态的存取（set/get/clear） | [working_memory.py](working_memory.py) |
| 现有 session 对话历史的写入与读取（add_turn/get_turns） | [episodic_memory.py](episodic_memory.py) |
| 统一记忆入口（同时访问 working + 会话历史兼容层） | [store.py](store.py) |
| 记忆 artifact、slot、决策等数据结构 | [types.py](types.py) |
| slot 定义、内置 slot、候选 artifact slot 校验 | [slots.py](slots.py) |
| SQLite FTS5 中文预分词、查询 term 生成、实体词注入 | [segmentation.py](segmentation.py) |
| 记忆冲突/写入决策审计日志 | [decision_log.py](decision_log.py) |
| Profile Store / Episode Store（Phase B，待实现） | 新建 `profile_memory_store.py` / `episode_memory_store.py`，并按需要接入 `store.py` |
| 语义记忆 / 向量检索（后续阶段，待实现） | 新建 `semantic_memory.py`，并按需要在 `store.py` 中注册 |

---

> 修改本目录或模块后，请同步更新此 README。
