# memory

> 上级索引：[sebastian/](../README.md)

## 模块职责

提供三层记忆抽象供 Agent 使用：**工作记忆**（进程内、任务作用域的临时状态）、**情节记忆**（基于 SQLite 的持久化对话历史）以及统一入口 `MemoryStore`。语义记忆（向量检索）为 Phase 3+ 规划能力，当前未实现。

## 目录结构

```
memory/
├── __init__.py          # 空，包入口
├── store.py             # MemoryStore：统一聚合 working + episodic 两层记忆
├── working_memory.py    # WorkingMemory：进程内 dict，按 task_id 隔离，任务结束后清除
└── episodic_memory.py   # EpisodicMemory：持久化对话历史，底层依赖 SessionStore
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 任务临时状态的存取（set/get/clear） | [working_memory.py](working_memory.py) |
| 对话历史的写入与读取（add_turn/get_turns） | [episodic_memory.py](episodic_memory.py) |
| 统一记忆入口（同时访问 working + episodic） | [store.py](store.py) |
| 语义记忆 / 向量检索（Phase 3+，待实现） | 新建 `semantic_memory.py`，并在 `store.py` 中注册 |

---

> 修改本目录或模块后，请同步更新此 README。
