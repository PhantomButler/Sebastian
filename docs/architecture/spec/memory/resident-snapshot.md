---
version: "1.1"
last_updated: 2026-05-03
status: implemented
---

# 常驻记忆快照（Resident Memory Snapshot）

*← [Memory 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 背景

Sebastian 当前已有长期记忆读取路径：`BaseAgent._memory_section()`。这条路径是动态的：每轮根据最新用户消息运行轻量 retrieval planner，按 lane 检索相关记忆，只在本轮 system prompt 中注入结果。

这对上下文回忆有价值，但不适合承载"每轮都应该稳定出现"的用户基础画像。如果当前消息没有触发 planner，模型可能看不到用户偏好的语言、称呼方式、回复风格等基础信息。

本设计新增一条常驻记忆路径，用于稳定注入高置信、低风险的用户画像事实。现有动态检索路径继续保留，但职责重新收窄为：提供本轮相关的历史证据和上下文，而不是承载用户基础画像。

---

## 2. 目标

- 每轮稳定注入一小段高置信用户画像记忆
- SQLite 记忆表仍是唯一真实来源；快照文件只是派生缓存
- 避免每轮为了常驻画像读取数据库
- 保留动态检索，用于本轮相关的回忆和上下文
- 快照文件放在 `settings.user_data_dir / "memory"` 下（数据目录 v2 布局）

本阶段不做：pin 管理 UI/API、自然语言"固定记住这个"流程、从 inferred memory 到 pinned memory 的自动提升。

---

## 3. 术语

| 术语 | 说明 |
|------|------|
| **Resident Memory** | 预期影响多数对话的记忆。只要可用，每轮都会注入。典型例子：回复语言、风格、用户称呼 |
| **Dynamic Retrieved Memory** | 由 retrieval planner 根据当前用户消息选择的记忆，临时性 |
| **Pinned Notes** | 带有 `policy_tags=["pinned"]` 的记录。本阶段不实现创建/删除 pinned 记录的机制 |

---

## 4. 架构

两条明确路径：

1. **`_resident_memory_section()`**：从预渲染 Markdown 快照文件读取，热路径不查数据库
2. **`_memory_section()`（dynamic）**：保留现有行为，针对当前消息执行 planner → lane fetch → assemble，允许返回空

`resident/` 子包边界：

| 文件 | 职责 |
|------|------|
| `resident_snapshot.py` | 快照路径、metadata 状态机、读写锁、dirty 标记、原子重建 |
| `resident_dedupe.py` | `canonical_bullet`、`slot_value_dedupe_key` 等去重纯函数 |

`resident/` 不依赖 `services/`；快照刷新器由 gateway startup 构造，并注入 `MemoryService` 与 `SessionConsolidationWorker`。

Prompt 组装顺序：

```
Base system prompt
## Resident Memory   ← 常驻快照（每轮稳定）
## Retrieved Memory  ← 动态检索（本轮相关）
## Session Todos
```

注入边界：只对 owner 会话中 Sebastian depth 1 生效。depth ≥ 2 的 agent 不接收常驻记忆。全局 memory settings 关闭时，常驻记忆也不注入。

---

## 5. 快照文件

```
<settings.user_data_dir>/memory/resident_snapshot.md
<settings.user_data_dir>/memory/resident_snapshot.meta.json
```

默认路径：`~/.sebastian/data/memory/`。这些文件是派生产物，可被删除后从数据库重建。

`resident_snapshot.meta.json` 结构：

```json
{
  "schema_version": 1,
  "generated_at": "2026-04-26T00:00:00Z",
  "snapshot_state": "ready",
  "generation_id": "01J...",
  "source_max_updated_at": "2026-04-26T00:00:00Z",
  "markdown_hash": "sha256:...",
  "record_hash": "sha256:...",
  "source_record_ids": ["..."],
  "rendered_record_ids": ["..."],
  "rendered_dedupe_keys": ["slot_value:sha256:..."],
  "rendered_canonical_bullets": ["用户偏好使用中文交流。"],
  "record_count": 2
}
```

`snapshot_state` 状态机：

| State | 含义 | 读取行为 |
|-------|------|----------|
| `ready` | 已从当前 DB 视图成功重建 | 校验通过后提供 Markdown |
| `dirty` | 已提交的记忆变更可能影响 resident 资格 | 返回空，并调度重建 |
| `rebuilding` | 正在重建 | 返回空 |
| `error` | dirty 后最近一次重建失败 | 返回空 |

读取端提供 Markdown 的条件（三者同时满足）：

```
snapshot_state = "ready"
resident_snapshot.md 存在
sha256(resident_snapshot.md bytes) == markdown_hash
```

---

## 6. 选择规则

公共过滤条件：

```
scope = "user"
subject_id = "owner"
status = "active"
confidence >= 0.8
valid_from is null or valid_from <= now
valid_until is null or valid_until > now
policy_tags 不含 "do_not_auto_inject"
policy_tags 不含 "needs_review"
policy_tags 不含 "sensitive"
```

通过公共过滤后，还必须满足任一：

1. `slot_id` 在 resident profile allowlist 中
2. `policy_tags` 包含 `pinned`，且满足 pinned eligibility contract

初始 resident profile allowlist：

```
user.profile.name
user.profile.location
user.profile.occupation
user.preference.language
user.preference.response_style
user.preference.addressing
```

Pinned eligibility contract（本阶段）：

```
source 为 "explicit" 或 "system_derived"
content 长度 <= 300 字符
content 不含 Markdown heading markers
content 不含 fenced code block
content 不含工具/系统/developer 指令性语言
```

Pinned 记录不豁免公共过滤。`pinned` 但 `sensitive` 或低置信的记录在本阶段跳过。

---

## 7. 渲染

快照 Markdown 结构：

```markdown
## Resident Memory

### Core Profile
- Profile memory: 用户偏好使用中文交流。
- Profile memory: 用户偏好回答简洁、直接。

### Pinned Notes
- Pinned memory: ...
```

渲染规则：

- 没有 allowlisted profile records → 省略 `Core Profile`
- 没有 pinned records → 省略 `Pinned Notes`
- 两个 subsection 都为空 → 整个文件内容为空
- 每条 bullet 必须被框定为"关于用户的记忆数据"，不能像给 assistant 的指令
- `Core Profile` 最多 8 条，`Pinned Notes` 最多 10 条
- 每条渲染后的 bullet 最多 300 字符
- Profile records 按 allowlist 顺序排序，再按 `updated_at` 降序
- Pinned records 按 `confidence` 降序，再按 `updated_at` 降序

去重规则：

- 同一记录同时满足 allowlist 与 `pinned` → 只进 `Core Profile`
- 去重维度：record id → canonical bullet → `slot_value` dedupe key
- `slot_value` key：`slot_value:sha256(canonical_json([subject_id, slot_id, structured_payload.value]))`
- `canonical_json` 使用稳定字段顺序、UTF-8、无多余空白
- `rendered_dedupe_keys`、`rendered_record_ids`、`rendered_canonical_bullets` 必须与最终渲染结果一致，供动态检索阶段过滤重复

---

## 8. 刷新生命周期

### `ResidentMemorySnapshotRefresher` 职责

- `rebuild()`：查询符合条件的 profile records，渲染 Markdown，原子写入 Markdown 与 metadata
- `schedule_refresh()`：debounce refresh 请求，让短时间内聚集的记忆写入只触发一次快照重写

> **实现增强**：spec 描述的 `mark_dirty()` 在实现中拆成 `mutation_scope()` 上下文管理器 + `mark_dirty_locked()` 两步。调用方必须先通过 `async with refresher.mutation_scope()` 持有 write side，再调 `mark_dirty_locked()`，否则抛 `RuntimeError`。语义等价，但接口显式强制了锁顺序，防止 DB commit 与脏标记之间出现无保护窗口。

### 进程内同步原语（Resident Snapshot Barrier）

使用 async read/write lock 实现：

- **Resident reads**：校验 metadata 和读取 Markdown 前获取 read side
- **Memory mutations**：从 DB commit 前到 `mark_dirty_locked()` 完成期间持有 write side（通过 `mutation_scope()`）
- **Snapshot publication**：替换 ready metadata 前获取 write side

此 barrier 为进程内机制。Sebastian 当前 gateway runtime 是单进程；多 writer process 场景须先扩展本 spec。

### 启动行为

1. `ensure_data_dir()` 创建数据目录布局
2. Gateway startup 初始化 memory storage
3. Resident snapshot refresher 执行一次 `rebuild()`
4. 即使 rebuild 失败，startup 也继续；失败写日志，常驻记忆在下一次成功刷新前为空

### 写入行为

1. 可能影响 resident eligibility 的记忆变更通过 `mutation_scope()` 持有 write side
2. Memory write pipeline 提交数据库变更
3. 在释放 write side 前，调用方触发 `mark_dirty_locked()`
4. `mark_dirty_locked()` 先递增 `dirty_generation`，再写入 `snapshot_state = "dirty"` 的 metadata，并把 `resident_snapshot.md` 替换为空文件
5. Refresher 在事务外调度 debounce refresh

### Ready snapshot 写入（原子性保证）

1. 渲染 Markdown bytes，计算 `markdown_hash`
2. 写入 `resident_snapshot.md.tmp`
3. 替换 `resident_snapshot.md`
4. 写入 `resident_snapshot.meta.json.tmp`（`snapshot_state = "ready"`，含 `generation_id` 与 `markdown_hash`）
5. 替换 `resident_snapshot.meta.json`

如果进程在第 3 步之后、第 5 步之前崩溃，旧 metadata 会保留，读取端因 `markdown_hash` 不匹配而不提供内容。

### Rebuild 版本校验（防止旧视图覆盖脏标记）

1. Rebuild 开始时读取当前 `dirty_generation`
2. 不持有 write side 的情况下查询 DB 并渲染 Markdown
3. 发布前获取 write side
4. 只有当前 `dirty_generation` 等于开始时观察到的 generation，才能发布；否则丢弃本次结果并重新调度

---

## 9. 错误处理

常驻记忆是增强能力，不是硬依赖：

| 情况 | 行为 |
|------|------|
| 快照文件缺失 | 返回空 resident section |
| 快照读取失败 | 写 warning，返回空 |
| Metadata mismatch | 尽力写 `dirty`，调度 rebuild，返回空 |
| dirty 后 rebuild 失败 | 写 `snapshot_state = "error"` + 空 Markdown，继续运行 |
| 没有符合条件的记录 | 写空 Markdown + `record_count = 0` 的 metadata |

Dirty 后不允许继续提供 last-known-good resident memory。只有 metadata 仍为 `ready` 且没有 mutation 把 snapshot 标记 dirty 时，才允许使用旧快照。

---

## 10. 动态检索重新定位

`BaseAgent._memory_section()` 收窄语义：

- 它是 dynamic retrieved memory section
- 在很多 turn 返回空是预期行为
- 不再负责稳定注入用户基础画像
- 继续只对 Sebastian depth 1 生效
- 继续独立于 `memory_search`，后者显式搜索所有 lanes

动态召回去重规则（过滤已由常驻记忆注入的记录）：

- memory id 出现在 `rendered_record_ids` → 跳过
- 可构造的 `slot_value` key 出现在 `rendered_dedupe_keys` → 跳过
- 渲染后的 canonical bullet 出现在 `rendered_canonical_bullets` → 跳过

`memory_search` 工具不受此过滤影响，仍可显式返回这些记录。

---

## 11. 测试

### 单元测试（`tests/unit/memory/`）

- snapshot builder 过滤规则（confidence、policy_tags、status、validity、allowlist）
- renderer 省略空 subsection、全局去重（record id / canonical bullet / `slot_value` key）
- 同一记录满足 allowlist + pinned 时只进 `Core Profile`
- metadata 字段与最终 Markdown 内容一致
- `slot_value` key 使用稳定 canonical JSON + SHA-256
- 快照路径在 `settings.user_data_dir / "memory"`
- 文件缺失或不可读时返回空字符串
- 原子写入写 Markdown 与 metadata
- dirty 后阻止 reader 提供旧内容，rebuild 失败写 `error` 状态
- metadata mismatch 返回空并调度 rebuild
- 崩溃场景不留 ready 的 Markdown/metadata 混合状态
- in-flight rebuild 不能在后续 dirty generation 后发布 stale ready metadata

### BaseAgent 测试

- Prompt 顺序：base → resident → dynamic → todos
- Dynamic retrieval 返回空 ≠ resident memory 为空
- 热路径读取 resident Markdown 时不访问 SQLite
- Dynamic 自动注入过滤 resident 中已出现的 record id / `slot_value` key / canonical bullet
- `memory_search` 工具不受 resident 去重过滤影响

### 集成测试

- Gateway startup 在数据目录初始化后重建 resident snapshot
- 记忆写入后 dirty refresh 在 DB transaction 外更新 snapshot

---

## 12. 延后工作

- `memory_pin` / `memory_unpin` owner-only 管理 API
- Android / Web UI，用于 pin、unpin、review 被跳过的 pinned records
- Cross-session consolidation 产生自动 pin 建议
- Sensitive memory 脱敏与按策略注入
- 兼容面审查后将 `_memory_section()` 重命名为 `_dynamic_memory_section()`

---

*← [Memory 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
