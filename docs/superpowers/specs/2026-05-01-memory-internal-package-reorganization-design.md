---
version: "0.1"
last_updated: 2026-05-01
status: draft
integrated_to: memory/overview.md
integrated_at: 2026-05-03
---

# Memory 内部包结构重组设计

## 1. 背景

P0 已经为 Sebastian memory 模块建立了 `MemoryService` 顶层 facade：

- `BaseAgent._memory_section()` 通过 `MemoryService.retrieve_for_prompt()` 获取动态记忆注入。
- `memory_search` 工具通过 `MemoryService.search()` 执行显式搜索。
- `memory_save` 工具通过 `MemoryService.write_candidates()` 写入候选记忆。
- `SessionConsolidationWorker` 通过 `MemoryService.write_candidates_in_session()` 复用写入 pipeline。

这一步已经把外部调用方从 `retrieval.py`、`pipeline.py`、store 文件等内部实现上解耦出来。现在剩下的问题是：`sebastian/memory/` 顶层仍然同时放着 store、retrieval、writing、consolidation、resident snapshot、LLM prompt 等不同职责的文件。

这种扁平结构会让后续升级变困难。比如未来要升级检索为 graph-routed retrieval，或给 consolidation 增加 cross-session worker，开发者仍然需要在一个大目录里区分哪些文件属于当前变更范围。

P1 的目标是进行行为不变的内部目录重组，让 memory 模块内部边界与 P0 facade 边界对齐。

## 2. 目标

P1 只做 `sebastian/memory` 内部实现文件归位：

1. 将现有内部实现文件按职责移动到子包。
2. 全仓更新 import path，不保留旧路径 shim。
3. 保持所有运行时行为、工具输出、prompt 文案、数据库 schema 不变。
4. 同步 README 与 architecture spec，使文档路径和实际代码结构一致。
5. 为后续 retrieval、writing、consolidation、resident snapshot 的独立升级建立清晰边界。

完成后，memory 模块应呈现为：

- 外部边界：`contracts/` + `services/`。
- 内部实现：`stores/`、`writing/`、`retrieval/`、`consolidation/`、`resident/`。
- 跨链路基础模块：保留在 `sebastian/memory/` 根目录。

## 3. 非目标

P1 不做以下事情：

- 不修改数据库 schema 或 migration。
- 不修改 `CandidateArtifact`、`MemoryArtifact`、slot、decision log 等数据模型。
- 不修改 `MemoryService` 对外方法签名。
- 不修改 `memory_save` / `memory_search` 的用户可见输入输出。
- 不修改 prompt section 的文案、顺序或检索注入格式。
- 不修改 retrieval planner、lane budget、confidence threshold、resident dedupe 行为。
- 不引入 embedding、vector index、graph retrieval 或 M-flow 风格拓扑检索。
- 不实现 cross-session consolidation、maintenance worker、summary replacement 或 exclusive relation 新行为。
- 不做类名、函数名、文件内部职责拆分。
- 不保留旧路径 compatibility shim。

本次是内部包结构整理，不是功能升级。

## 4. 目标目录结构

P1 后的 `sebastian/memory/` 结构应为：

```text
sebastian/memory/
  __init__.py
  README.md
  constants.py
  data-flow.md
  errors.py
  startup.py
  store.py
  subject.py
  trace.py
  types.py
  working_memory.py

  contracts/
    __init__.py
    retrieval.py
    writing.py

  services/
    __init__.py
    memory_service.py
    retrieval.py
    writing.py

  stores/
    __init__.py
    profile_store.py
    episode_store.py
    entity_registry.py
    slot_definition_store.py

  writing/
    __init__.py
    pipeline.py
    resolver.py
    write_router.py
    decision_log.py
    feedback.py
    slot_proposals.py
    slots.py

  retrieval/
    __init__.py
    retrieval.py
    retrieval_lexicon.py
    depth_guard.py
    segmentation.py

  consolidation/
    __init__.py
    consolidation.py
    extraction.py
    prompts.py
    provider_bindings.py

  resident/
    __init__.py
    resident_snapshot.py
    resident_dedupe.py
```

根目录保留跨链路基础模块：

- `types.py`：memory artifact、slot、decision、enum 等核心类型。
- `subject.py`：subject 解析规则。
- `trace.py`：memory trace 日志辅助。
- `constants.py`：跨子包常量。
- `errors.py`：异常体系。
- `startup.py`：memory storage / FTS / slot registry 启动初始化入口。
- `store.py` / `working_memory.py`：既有 working memory 公共入口。

这些模块不归入某个业务子包，避免制造反向依赖。

`store.py` / `working_memory.py` 的“公共入口”只指现有 working memory 能力。P1 不允许在这些文件里为本次迁移的旧模块路径或 moved store class 新增 re-export。

## 5. 文件迁移表

| 旧路径 | 新路径 | 说明 |
|--------|--------|------|
| `sebastian/memory/profile_store.py` | `sebastian/memory/stores/profile_store.py` | Profile store CRUD |
| `sebastian/memory/episode_store.py` | `sebastian/memory/stores/episode_store.py` | Episode / summary store 与 FTS |
| `sebastian/memory/entity_registry.py` | `sebastian/memory/stores/entity_registry.py` | Entity registry CRUD 与 trigger reload |
| `sebastian/memory/slot_definition_store.py` | `sebastian/memory/stores/slot_definition_store.py` | `memory_slots` DB CRUD |
| `sebastian/memory/pipeline.py` | `sebastian/memory/writing/pipeline.py` | candidate 写入 pipeline |
| `sebastian/memory/resolver.py` | `sebastian/memory/writing/resolver.py` | 冲突解析 |
| `sebastian/memory/write_router.py` | `sebastian/memory/writing/write_router.py` | 持久化路由 |
| `sebastian/memory/decision_log.py` | `sebastian/memory/writing/decision_log.py` | decision log 写入 |
| `sebastian/memory/feedback.py` | `sebastian/memory/writing/feedback.py` | `memory_save` 结果摘要 |
| `sebastian/memory/slot_proposals.py` | `sebastian/memory/writing/slot_proposals.py` | 动态 slot 注册与校验 |
| `sebastian/memory/slots.py` | `sebastian/memory/writing/slots.py` | slot registry 与 builtin slots |
| `sebastian/memory/retrieval.py` | `sebastian/memory/retrieval/retrieval.py` | retrieval planner / assembler |
| `sebastian/memory/retrieval_lexicon.py` | `sebastian/memory/retrieval/retrieval_lexicon.py` | lane 触发词 |
| `sebastian/memory/depth_guard.py` | `sebastian/memory/retrieval/depth_guard.py` | memory depth guard |
| `sebastian/memory/segmentation.py` | `sebastian/memory/retrieval/segmentation.py` | FTS 中文分词与实体词注入 |
| `sebastian/memory/consolidation.py` | `sebastian/memory/consolidation/consolidation.py` | session consolidation worker / scheduler |
| `sebastian/memory/extraction.py` | `sebastian/memory/consolidation/extraction.py` | MemoryExtractor |
| `sebastian/memory/prompts.py` | `sebastian/memory/consolidation/prompts.py` | extractor / consolidator prompt 构建 |
| `sebastian/memory/provider_bindings.py` | `sebastian/memory/consolidation/provider_bindings.py` | memory component binding 常量 |
| `sebastian/memory/resident_snapshot.py` | `sebastian/memory/resident/resident_snapshot.py` | resident snapshot refresher |
| `sebastian/memory/resident_dedupe.py` | `sebastian/memory/resident/resident_dedupe.py` | resident dedupe helpers |

`contracts/` 与 `services/` 已在 P0 中建立，本次保持路径不变。

## 6. 分组依据

### 6.1 `stores/`

`stores/` 放数据库访问与领域记录 CRUD。它们的职责是读写 DB record，不应该知道 service facade、gateway state 或后台调度策略。

包含：

- `profile_store.py`
- `episode_store.py`
- `entity_registry.py`
- `slot_definition_store.py`

### 6.2 `writing/`

`writing/` 放 candidate artifact 从校验到落库的写入链路。动态 slot 注册也放在这里，因为当前它服务于 extractor / consolidator 提议 slot 后的写入阶段。

包含：

- `pipeline.py`
- `resolver.py`
- `write_router.py`
- `decision_log.py`
- `feedback.py`
- `slot_proposals.py`
- `slots.py`

`slot_definition_store.py` 不放在这里，因为它是 DB CRUD store，而不是写入流程控制器。

### 6.3 `retrieval/`

`retrieval/` 放自动 prompt 注入和显式搜索背后的检索策略、分词、lane planner 与 depth guard。

包含：

- `retrieval.py`
- `retrieval_lexicon.py`
- `depth_guard.py`
- `segmentation.py`

`segmentation.py` 虽然也影响写入后的 FTS 可检索性，但当前职责主要是检索索引与查询 term 生成，归入 retrieval 更贴近实际用途。

### 6.4 `consolidation/`

`consolidation/` 放后台沉淀、LLM 提取、prompt 构建、memory component binding 常量。

包含：

- `consolidation.py`
- `extraction.py`
- `prompts.py`
- `provider_bindings.py`

P1 不拆 `consolidation.py` 内部 worker / scheduler / models。后续如果实现 cross-session consolidation 或 maintenance worker，再单独设计是否拆文件。

### 6.5 `resident/`

`resident/` 放常驻记忆快照基础设施。

包含：

- `resident_snapshot.py`
- `resident_dedupe.py`

`resident/` 不依赖 `services/`，避免 snapshot 基础设施反向依赖 service facade。

## 7. 依赖方向

P1 后的依赖方向必须保持清晰：

```text
external callers
  -> memory.contracts / memory.services
      -> memory.consolidation
      -> memory.retrieval
      -> memory.writing
      -> memory.resident
      -> memory.stores
```

具体规则：

1. `services/` 可以调用内部子包。
2. `consolidation/` 可以调用 `writing/`、`stores/`、`retrieval/` 和根基础模块。
3. `writing/` 可以调用 `stores/` 和根基础模块。
4. `retrieval/` 可以调用 `stores/` 和根基础模块。
5. `resident/` 可以调用 `stores/` 和根基础模块，但不能依赖 `services/`。
6. `stores/` 不能依赖 `services/`、`consolidation/`、`resident/`。
7. 根基础模块不能依赖业务子包。

`SessionConsolidationWorker` 有两个明确例外：

1. 它可以通过构造函数接收 `MemoryService`，并调用 `MemoryService.write_candidates_in_session()`。这个依赖必须保持为注入依赖，不能在 `consolidation/` 内读取 gateway global state，也不能让 consolidation 自行构造 `MemoryService`。

2. 它还可以通过构造函数接收 `ResidentMemorySnapshotRefresher | None`（可选注入），用于在沉淀写入后调用 `mark_dirty_locked()` 标记 resident snapshot 为脏。该依赖必须保持为注入依赖，不能在 `consolidation/` 内自行构造 `ResidentMemorySnapshotRefresher`。`consolidation/` 对 `resident/` 的 import 仅限 `if TYPE_CHECKING:` 块（仅用于类型标注），运行时依赖通过构造函数注入传入。

外部模块包括 `sebastian/core`、`sebastian/gateway`、`sebastian/capabilities/tools` 等。它们的 memory 业务调用应继续通过 `MemoryService` / `contracts`，不应新增对 `stores/`、`writing/`、`retrieval/` 的直接业务依赖。

Gateway startup 是运行时装配层，P1 保持现有装配职责，不在本次引入新的 bootstrap facade。允许 `sebastian/gateway/app.py` 直接 import 下列 memory 内部组件，且仅用于 startup / shutdown 装配：

- `sebastian.memory.startup.init_memory_storage()`、`seed_builtin_slots()`、`bootstrap_slot_registry()`：memory storage / FTS / slot registry 初始化。
- `sebastian.memory.stores.entity_registry.EntityRegistry`：启动时 bootstrap planner entity triggers。
- `sebastian.memory.retrieval.retrieval.DEFAULT_RETRIEVAL_PLANNER`：启动时 bootstrap / reload entity triggers。
- `sebastian.memory.writing.slots.DEFAULT_SLOT_REGISTRY`：seed / bootstrap slot registry。
- `sebastian.memory.consolidation.consolidation.MemoryConsolidationScheduler`、`MemoryConsolidator`、`SessionConsolidationWorker`、`sweep_unconsolidated`：装配 session consolidation。
- `sebastian.memory.consolidation.extraction.MemoryExtractor`：装配 `memory_save` 工具后台提取器。
- `sebastian.memory.resident.resident_snapshot.ResidentMemorySnapshotRefresher`：装配 resident snapshot refresher。
- `sebastian.memory.services.MemoryService`：创建唯一 runtime service facade。

这些 gateway startup import 不允许用于请求处理路径直接读写 memory 业务数据。若未来要收口这些装配细节，应另开 spec 设计 `bootstrap_memory_runtime(...)` 之类的启动封装。

其他例外：

- tests 可以 import 内部子包做单元测试。
- 文档、graphify、开发脚本不受运行时依赖方向约束，但路径需要同步。

## 8. Import 迁移策略

本次不保留旧路径 shim。迁移后，旧 import 必须在仓库内清零。

示例：

```python
# before
from sebastian.memory.profile_store import ProfileMemoryStore
from sebastian.memory.pipeline import process_candidates
from sebastian.memory.retrieval import DEFAULT_RETRIEVAL_PLANNER

# after
from sebastian.memory.stores.profile_store import ProfileMemoryStore
from sebastian.memory.writing.pipeline import process_candidates
from sebastian.memory.retrieval.retrieval import DEFAULT_RETRIEVAL_PLANNER
```

实施建议：

1. 用 `git mv` 移动文件，保留 Git history。
2. 用 PyCharm MCP 索引搜索旧 import path。
3. 对每个旧路径做精确替换。
4. 更新测试中的 monkeypatch target。
5. 跑 lint / compile / tests。
6. 再次搜索旧路径，确认清零。

不使用 `sed` 之类大范围盲替换来改代码。需要机械替换时，也应先用索引搜索确认命中范围。

## 9. `__init__.py` 规则

`contracts/` 和 `services/` 是外部边界包，可以继续在 `__init__.py` 中导出 contract 和 service class。

其他内部子包的 `__init__.py` 默认保持空或只放简短包说明，不建立复杂 barrel import。

原因：

- 减少循环 import 风险。
- 让调用方显式依赖具体内部模块。
- 避免把内部子包误用成新的公共 API。

例如不推荐：

```python
from sebastian.memory.writing import process_candidates
```

推荐：

```python
from sebastian.memory.writing.pipeline import process_candidates
```

## 10. 文档同步

P1 必须同步以下文档：

- `sebastian/memory/README.md`
- `sebastian/README.md`
- `docs/architecture/spec/memory/INDEX.md`
- `docs/architecture/spec/memory/overview.md`
- `docs/architecture/spec/memory/retrieval.md`
- `docs/architecture/spec/memory/storage.md`
- `docs/architecture/spec/memory/write-pipeline.md`
- `docs/architecture/spec/memory/consolidation.md`
- `docs/architecture/spec/memory/implementation.md`
- `docs/architecture/spec/memory/resident-snapshot.md`

实际实施时，应同步 `docs/architecture/spec/memory/*.md` 中所有旧路径引用；上面列表只是重点文件。

同步内容：

1. 更新目录结构。
2. 更新修改导航。
3. 更新 P0 facade 后面的内部实现路径。
4. 修正文档中旧路径引用。
5. 修正文档中可能混淆的 `data-flow.md` 路径引用。

`sebastian/memory/data-flow.md` 当前在模块目录内，而不是 `docs/architecture/spec/memory/data-flow.md`。P1 不强制移动该文档，但引用必须准确。

## 11. 验证

P1 实现完成后必须运行：

```bash
ruff check sebastian tests
python -m compileall sebastian
python -m compileall tests
pytest tests/unit/memory -q
pytest tests/unit/memory/test_memory_imports_after_reorg.py -q
pytest tests/unit/capabilities/test_memory_tools.py -q
pytest tests/integration/memory -q
python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"
```

P1 implementation plan 必须新增一个 import smoke test，例如 `tests/unit/memory/test_memory_imports_after_reorg.py`。该测试不验证行为，只验证迁移后 import target 可解析，至少覆盖：

1. 本 spec §5 中所有 moved modules 的新路径。
2. `sebastian.core.base_agent`。
3. `sebastian.gateway.app`。
4. `sebastian.capabilities.tools.memory_save`。
5. `sebastian.capabilities.tools.memory_search`。

该 smoke test 不应遍历并 import 全部 `sebastian.*` 模块，因为部分入口可能有启动副作用或外部环境依赖；它应显式列出本次迁移影响的模块和关键外部入口。

如果修改触达 gateway startup 或 capability tool import，还应补跑相关聚焦测试：

```bash
pytest tests/unit/capabilities/test_memory_tools.py -q
pytest tests/integration/memory/test_session_consolidation_proposes_slots.py -q
```

完成后还需要搜索旧路径。搜索必须使用精确 import pattern，避免合法新路径被 substring 误伤。

禁止的旧 import 形式包括：

```text
from sebastian.memory.profile_store import ...
import sebastian.memory.profile_store
from sebastian.memory.episode_store import ...
import sebastian.memory.episode_store
from sebastian.memory.entity_registry import ...
import sebastian.memory.entity_registry
from sebastian.memory.slot_definition_store import ...
import sebastian.memory.slot_definition_store
from sebastian.memory.pipeline import ...
import sebastian.memory.pipeline
from sebastian.memory.resolver import ...
import sebastian.memory.resolver
from sebastian.memory.write_router import ...
import sebastian.memory.write_router
from sebastian.memory.decision_log import ...
import sebastian.memory.decision_log
from sebastian.memory.feedback import ...
import sebastian.memory.feedback
from sebastian.memory.slot_proposals import ...
import sebastian.memory.slot_proposals
from sebastian.memory.slots import ...
import sebastian.memory.slots
from sebastian.memory.retrieval import ...
import sebastian.memory.retrieval as ...
from sebastian.memory.retrieval_lexicon import ...
import sebastian.memory.retrieval_lexicon
from sebastian.memory.depth_guard import ...
import sebastian.memory.depth_guard
from sebastian.memory.segmentation import ...
import sebastian.memory.segmentation
from sebastian.memory.consolidation import ...
import sebastian.memory.consolidation as ...
from sebastian.memory.extraction import ...
import sebastian.memory.extraction
from sebastian.memory.prompts import ...
import sebastian.memory.prompts
from sebastian.memory.provider_bindings import ...
import sebastian.memory.provider_bindings
from sebastian.memory.resident_snapshot import ...
import sebastian.memory.resident_snapshot
from sebastian.memory.resident_dedupe import ...
import sebastian.memory.resident_dedupe
```

也禁止包级 submodule import：

```text
from sebastian.memory import profile_store
from sebastian.memory import episode_store
from sebastian.memory import entity_registry
from sebastian.memory import slot_definition_store
from sebastian.memory import pipeline
from sebastian.memory import resolver
from sebastian.memory import write_router
from sebastian.memory import decision_log
from sebastian.memory import feedback
from sebastian.memory import slot_proposals
from sebastian.memory import slots
from sebastian.memory import retrieval
from sebastian.memory import retrieval_lexicon
from sebastian.memory import depth_guard
from sebastian.memory import segmentation
from sebastian.memory import consolidation
from sebastian.memory import extraction
from sebastian.memory import prompts
from sebastian.memory import provider_bindings
from sebastian.memory import resident_snapshot
from sebastian.memory import resident_dedupe
```

带别名的同类形式也必须迁移，例如 `from sebastian.memory import entity_registry as er_mod`。

合法新 import 示例：

```python
from sebastian.memory.retrieval.retrieval import DEFAULT_RETRIEVAL_PLANNER
from sebastian.memory.consolidation.consolidation import SessionConsolidationWorker
```

这些旧路径在运行时代码、测试、README 和 architecture docs 中都不应继续出现，除非是在本设计文档、changelog 或明确标注的迁移说明中作为历史路径引用。`docs/architecture/spec/memory/` 和 `sebastian/memory/README.md` 应描述迁移后的当前结构，不保留旧实现路径。

## 12. 验收标准

P1 完成时必须满足：

1. `sebastian/memory` 顶层只保留基础模块、`contracts/`、`services/` 和新内部子包。
2. 全仓 import 已迁移到新路径。
3. 不存在旧路径 shim 文件。
4. `MemoryService` 对外 API 不变。
5. `memory_save` / `memory_search` 用户可见行为不变。
6. Session consolidation 行为不变。
7. Resident snapshot 注入与 dirty 标记行为不变。
8. 数据库 schema 无变化。
9. Prompt 文案与注入顺序无变化。
10. 文档路径与代码结构一致。
11. 验证命令全部通过。

## 13. 风险与控制

### 13.1 Import 漏改

风险：文件移动后仍有旧 import，导致运行时 `ModuleNotFoundError`。

控制：

- PyCharm MCP 索引搜索旧路径。
- `ruff check` 捕获未解析 import。
- `python -m compileall sebastian/memory` 捕获语法和 import 基础问题。
- memory 单元测试和集成测试覆盖主链路。

### 13.2 Monkeypatch target 漏改

风险：测试 patch 旧路径，导致 patch 不生效或测试误测。

控制：

- 搜索 `monkeypatch.setattr`、`patch(` 中的 `sebastian.memory.` 字符串。
- 对 service tests、tool tests、consolidation tests 单独跑聚焦测试。

### 13.3 循环 import

风险：子包 `__init__.py` 过度 re-export，或依赖方向被打破。

控制：

- 内部子包 `__init__.py` 默认保持空。
- 保持显式模块 import。
- 不让 `stores/` 依赖 `services/` 或 `consolidation/`。

### 13.4 行为漂移

风险：迁移时顺手修改函数体、prompt、planner 或 pipeline 逻辑。

控制：

- 本次只允许 import path、文件路径、文档路径变化。
- review 时重点检查非 import diff。
- 现有 tests 必须通过。

## 14. 后续工作

P1 完成后，后续升级可以按子包独立设计：

- `retrieval/`：graph-routed retrieval、embedding-backed profile lane、M-flow 风格 bundle search。
- `writing/`：更强的 conflict resolver、summary replacement、exclusive relation 写入规则。
- `consolidation/`：cross-session consolidation、maintenance worker、周期性降权与重复压缩。
- `resident/`：更细的 snapshot 分层、按 scope / subject 生成多份快照。
- `stores/`：索引修复、查询性能优化、未来 schema 迁移。

这些都不属于 P1。
