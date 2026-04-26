---
version: "1.0"
last_updated: 2026-04-26
status: planned
---

# Resident Memory Snapshot（常驻记忆快照）设计

## 1. 背景

Sebastian 当前已有长期记忆读取路径：`BaseAgent._memory_section()`。
这条路径是动态的：每轮根据最新用户消息运行轻量 retrieval planner，按 lane 检索相关记忆，并只在本轮 system prompt 中注入结果。

这对上下文回忆有价值，但不适合承载“每轮都应该稳定出现”的用户基础画像。如果当前消息没有触发 planner，模型可能看不到用户偏好的语言、称呼方式、回复风格等基础信息。实际使用中，agent 往往更多依赖显式 `memory_search` 工具查记忆；这适合深查，但不适合每轮个性化。

本设计新增一条常驻记忆路径，用于稳定注入高置信、低风险的用户画像事实。现有动态检索路径继续保留，但职责重新收窄为：提供本轮相关的历史证据和上下文，而不是承载用户基础画像。

## 2. 目标

- 每轮稳定注入一小段高置信用户画像记忆。
- SQLite 记忆表仍是唯一真实来源；快照文件只是派生缓存。
- 避免每轮为了常驻画像读取数据库。
- 保留动态检索，用于本轮相关的回忆和上下文。
- 适配安装目录 v2：生成文件放在 `settings.user_data_dir` 下。
- 本阶段暂不做 pin 管理 UI/API，也不做自然语言“固定记住这个”流程。

## 3. 非目标

- 本阶段不新增 `memory_pin` 工具或 REST API。
- 本阶段不支持自然语言“固定记住这个”工作流。
- 本阶段不做从 inferred memory 到 pinned memory 的自动提升。
- 本阶段不把 sensitive memory 注入常驻记忆。
- 不替代 `memory_search`；显式搜索仍是深查入口。

## 4. 术语

### Resident Memory（常驻记忆）

预期影响多数对话的记忆。只要可用，每轮都会注入。典型例子包括回复语言、回复风格、用户偏好称呼、用户基础画像事实。

### Dynamic Retrieved Memory（动态召回记忆）

由 retrieval planner 根据当前用户消息选择的记忆。它可以包含当前上下文、历史证据、关系记录，或与本轮相关的画像记录。它是临时的：下一轮如果没有触发同一 lane，就不会再次出现。

### Pinned Notes（固定记忆备注）

带有 `policy_tags=["pinned"]` 的记录。常驻快照渲染器会支持这类记录，但本阶段不实现创建或删除 pinned 记录的机制。

## 5. 架构

记忆读取面拆成两条明确路径：

1. `resident_memory_section`
   - 从预渲染 Markdown 快照文件读取。
   - 每轮注入稳定、高置信的用户画像事实。
   - 热路径不查询数据库。

2. `dynamic_memory_section`
   - 保留现有 `_memory_section()` 行为。
   - 针对最新用户消息执行 planner → lane fetch → assemble。
   - 允许返回空字符串，这是正常行为。

Prompt 组装顺序：

```text
Base system prompt

## Resident Memory
...

## Retrieved Memory
...

## Session Todos
...
```

`BaseAgent._stream_inner()` 按以下顺序组装：

1. 构造基础 system prompt。
2. 读取 resident snapshot。
3. 执行动 dynamic memory retrieval。
4. 读取 session todos。
5. 按顺序拼接所有非空 section。

常驻记忆注入使用与长期自动记忆注入相同的高层访问边界：只注入 owner 会话中的 Sebastian depth 1。depth >= 2 的 agent 不在 system prompt 中接收常驻记忆。如果全局 memory settings 关闭，常驻记忆也不注入。

## 6. 快照文件

常驻记忆快照文件位于用户数据目录：

```text
<settings.user_data_dir>/memory/resident_snapshot.md
<settings.user_data_dir>/memory/resident_snapshot.meta.json
```

默认安装路径：

```text
~/.sebastian/data/memory/resident_snapshot.md
~/.sebastian/data/memory/resident_snapshot.meta.json
```

这些文件是派生产物。它们可以被删除，并从数据库重建。

`resident_snapshot.md` 是可直接注入 prompt 的 Markdown。

`resident_snapshot.meta.json` 存储运行元数据：

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

读取端必须先校验 metadata，才能提供 Markdown 内容。metadata 不只是调试信息，而是常驻记忆注入的 freshness 与安全门。

`snapshot_state` 状态：

| State | 含义 | 读取行为 |
| --- | --- | --- |
| `ready` | 快照已从当前 DB 视图成功重建。 | 校验通过后可以提供 Markdown。 |
| `dirty` | 已提交的记忆变更可能影响常驻记忆资格。 | 返回空，并调度重建。 |
| `rebuilding` | 正在重建。 | 返回空。 |
| `error` | 快照变 dirty 后，最近一次重建失败。 | 返回空。 |

`record_hash` 是所选记录 prompt 相关字段的确定性 hash：`id`、`content`、`slot_id`、`kind`、`confidence`、`status`、`valid_from`、`valid_until`、`policy_tags`、`updated_at`。
`source_max_updated_at` 是所选记录中最大的 `updated_at`。
`markdown_hash` 是 Markdown 文件字节内容的 SHA-256。
`rendered_record_ids` 是实际进入常驻快照正文的 memory record id 列表。
`rendered_dedupe_keys` 是动态检索去重使用的稳定 key 列表。
`rendered_canonical_bullets` 是最终 bullet 经过同一规范化 helper 处理后的文本，用于 exact bullet 去重。

metadata 文件是提交指针。读取端只有在满足以下条件时才能提供 Markdown：

```text
snapshot_state = "ready"
resident_snapshot.md 存在
sha256(resident_snapshot.md bytes) == markdown_hash
```

这可以防止进程在 Markdown 与 metadata 写入之间崩溃时产生“旧 metadata + 新 Markdown”的混合可服务状态。读取端不在热路径查询 SQLite 来证明 freshness。

## 7. 选择规则

SQLite 仍是真实来源。快照构建器读取 active memory records，只选择高置信、低风险条目。

公共过滤条件：

```text
scope = "user"
subject_id = "owner"
status = "active"
confidence >= 0.8
valid_from is null or valid_from <= now
valid_until is null or valid_until > now
policy_tags does not contain "do_not_auto_inject"
policy_tags does not contain "needs_review"
policy_tags does not contain "sensitive"
```

记录通过公共过滤后，还必须满足以下任一条件：

1. `slot_id` 在 resident profile allowlist 中。
2. `policy_tags` 包含 `pinned`，且满足本节 pinned eligibility contract。

初始 resident profile allowlist：

```text
user.profile.name
user.profile.location
user.profile.occupation
user.preference.language
user.preference.response_style
user.preference.addressing
```

如果这些 slot 中有任何一个不存在于 builtin slot registry，本功能应补齐为 builtin slot。allowlist 必须保持很小，不能包含所有 preference slot。食物、娱乐、购物等普通偏好不应该每轮进入 system prompt。

Pinned 记录不豁免公共过滤。pinned 但 sensitive 或低置信的记录在本阶段会被跳过。

本阶段 pinned eligibility contract：

```text
source is "explicit" or "system_derived"
content length <= 300 characters
content contains no Markdown heading markers
content contains no fenced code blocks
content contains no tool/system/developer instruction language
```

本阶段不提供 pin 创建或 owner review UI。pinned 路径只是为了让未来经过审核的 pins 可以复用同一套 snapshot 机制。如果现有手动种入的 pinned 记录不满足此契约，构建器必须跳过。

## 8. 渲染

快照渲染器输出紧凑 section：

```markdown
## Resident Memory

### Core Profile
- Profile memory: 用户偏好使用中文交流。
- Profile memory: 用户偏好回答简洁、直接。

### Pinned Notes
- Pinned memory: ...
```

规则：

- 没有 allowlisted profile records 时，省略 `Core Profile`。
- 没有 pinned records 时，省略 `Pinned Notes`。
- 两个 subsection 都为空时，整个文件内容为空。
- 每条 bullet 必须渲染为被框定的数据，而不是自由形式指令。
- Profile records 按 allowlist 顺序排序，再按 `updated_at` 降序。
- Pinned records 按 `confidence` 降序排序，再按 `updated_at` 降序。
- `Core Profile` 最多 8 条。
- `Pinned Notes` 最多 10 条。
- 每条渲染后的 bullet 最多 300 字符。
- 去除 Markdown heading、fenced code block、控制字符和开头 list marker。

这些上限用于保证常驻 section 足够小，可以安全地每轮注入。

去重规则：

- 同一 memory record 只能渲染一次。
- 同一记录同时满足 allowlist 与 `pinned` 时，优先进入 `Core Profile`，不再进入 `Pinned Notes`。`Pinned Notes` 只承载 allowlist 外的固定内容。
- 渲染前先构造一个全局候选序列，再按这个序列去重：
  1. `Core Profile` 候选：按 allowlist 顺序排序，再按 `updated_at` 降序。
  2. Allowlist 外的 `Pinned Notes` 候选：按 `confidence` 降序排序，再按 `updated_at` 降序。
- 去重按全局候选序列保留第一条。
- 去重维度依次为 record id、canonical bullet、`slot_value` dedupe key。
- Canonical bullet 由同一个渲染/规范化 helper 生成：去除大小写差异、首尾空白、Markdown 控制字符和开头 label 差异后比较。
- 对有 `slot_id` 和结构化值的 profile/preference 记录，构造 `slot_value` dedupe key：`slot_value:sha256(canonical_json([subject_id, slot_id, structured_payload.value]))`。
- `canonical_json` 必须使用稳定字段顺序、UTF-8、无多余空白；无 `structured_payload.value` 时不生成 `slot_value` key。
- `rendered_dedupe_keys` 只存 `slot_value` key；record id 去重使用 `rendered_record_ids`，exact bullet 去重使用 `rendered_canonical_bullets`。
- Metadata 中的 `rendered_record_ids`、`rendered_dedupe_keys`、`rendered_canonical_bullets` 必须与最终渲染结果一致，供动态检索阶段过滤重复内容。

Bullet 格式：

```markdown
- Profile memory: 用户偏好使用中文交流。
- Pinned memory: ...
```

措辞必须把内容框定为关于用户的记忆数据，而不是覆盖 system prompt 的指令。如果某条记录在规范化后仍像一条给 assistant 的指令，必须跳过。

## 9. 刷新生命周期

新增 `ResidentMemorySnapshotRefresher`。

职责：

- `rebuild()`
  - 查询符合条件的 profile records。
  - 渲染 Markdown。
  - 原子写入 Markdown 与 metadata。

- `mark_dirty()`
  - 在记忆状态变化后标记需要刷新。

- `schedule_refresh()`
  - debounce refresh 请求，让短时间内聚集的记忆写入只触发一次快照重写。

Refresher 拥有一个进程内同步原语：resident snapshot barrier。它可以实现为 async read/write lock 或等价的服务级锁。prompt-time resident reads 与 memory write dirty marking 都必须参与这个 barrier：

- Resident reads 在校验 metadata 和读取 Markdown 前获取 read side。
- Memory mutations 从 DB commit 前到 `mark_dirty()` 完成期间持有 write side。
- Snapshot publication 在替换 ready metadata 前获取 write side。

这个 barrier 有意设计为进程内机制。Sebastian 当前 gateway runtime 是单进程；如果未来支持多个 writer process，必须先用跨进程锁或 DB-backed revision protocol 扩展本 spec，才能在该模式下启用 resident snapshots。

启动行为：

1. `ensure_data_dir()` 创建数据目录布局。
2. Gateway startup 初始化 memory storage。
3. Resident snapshot refresher 执行一次 `rebuild()`。
4. 即使 rebuild 失败，startup 也继续；失败会写日志，常驻记忆在下一次成功刷新前为空。

写入行为：

1. 可能影响 resident eligibility 的记忆变更获取 resident snapshot barrier write side。
2. Memory write pipeline 提交数据库变更。
3. 在写 API 返回或释放 write side 前，调用方触发 `mark_dirty()`。
4. `mark_dirty()` 先递增 `dirty_generation`，然后立即写入 `snapshot_state = "dirty"` 的 metadata，并把 `resident_snapshot.md` 替换为空文件。
5. Refresher 在事务外调度 debounce refresh。

Refresher 不得在数据库事务内写快照文件。这样可以避免数据库 rollback 后，文件已经刷新成未提交状态。

Resident reader 在已提交的记忆变更可能影响 resident eligibility 后，绝不能继续提供变更前的旧快照。拿不准时，读取端返回空常驻 section，直到成功重建并写入 `snapshot_state = "ready"`。

DB commit 与 dirty metadata 之间的缝隙必须由 resident snapshot barrier 串行化。Prompt assembly 可以在 mutation commit 可见前与其并发，但不能在 writer 处于 DB commit 与 `mark_dirty()` 之间时读取 resident snapshot 文件。

Ready snapshot 写入以 metadata 作为最终提交指针：

1. 渲染 Markdown bytes，并计算 `markdown_hash`。
2. 写入 `resident_snapshot.md.tmp`。
3. 替换 `resident_snapshot.md`。
4. 写入 `resident_snapshot.meta.json.tmp`，其中 `snapshot_state = "ready"`，并包含 `generation_id` 与 `markdown_hash`。
5. 替换 `resident_snapshot.meta.json`。

如果进程在第 3 步之后、第 5 步之前崩溃，旧 metadata 会保留。因为读取端校验 `markdown_hash`，所以不会用旧 ready metadata 提供新 Markdown。

Rebuild publication 也必须对 dirty writes 做版本校验：

1. Rebuild 开始时读取 refresher 当前 `dirty_generation`。
2. 不持有 write side 的情况下查询 DB 并渲染 Markdown。
3. 发布 ready metadata 前，获取 barrier write side。
4. 只有当前 `dirty_generation` 仍等于开始时观察到的 generation，才能发布。
5. 如果 generation 已改变，丢弃本次渲染结果并重新调度 rebuild。

`mark_dirty()` 在写 dirty metadata 前先递增 `dirty_generation`。这可以防止基于旧 DB 视图的 in-flight rebuild 覆盖之后的 dirty marker，并写出过期的 ready metadata。

## 10. 错误处理

常驻记忆是增强能力，不是硬依赖。

- 快照文件缺失：返回空 resident section。
- 快照读取失败：写 warning，返回空 section。
- Metadata mismatch：尽力写入 `snapshot_state = "dirty"`，调度 rebuild，返回空。
- Dirty 后 rebuild 失败：写入 `snapshot_state = "error"` 和空 Markdown 文件；继续运行，但不注入 resident memory。
- 没有符合条件的记录：写入空 Markdown，并写入 `record_count = 0` 的 metadata。

Dynamic retrieval 失败保持现有行为：`_memory_section()` 写日志并返回空字符串。

Snapshot 被标记 dirty 后，不允许继续提供 last-known-good resident memory。只有 metadata 仍为 `ready` 且没有 mutation 把 snapshot 标记 dirty 时，才允许使用 last-known-good 行为。

## 11. 当前 `_memory_section()` 的重新定位

`BaseAgent._memory_section()` 当前是唯一自动记忆注入 hook。本设计收窄它的语义：

- 它是 dynamic retrieved memory section。
- 它在很多 turn 返回空是预期行为。
- 它不再负责稳定注入用户基础画像。
- 它继续只对 Sebastian depth 1 生效。
- 它继续独立于 `memory_search`，后者显式搜索所有 lanes。
- 它接收 resident snapshot metadata 中的 `rendered_record_ids`、`rendered_dedupe_keys` 与 `rendered_canonical_bullets`，在 assemble 前过滤已由常驻记忆注入的记录。

第一版实现可以保留方法名以降低兼容风险，但文档和测试应把它描述为 dynamic retrieval。后续如果调用面足够小，可以再单独清理命名为 `_dynamic_memory_section()`。

动态召回去重规则：

- 如果动态检索结果的 memory id 出现在 `rendered_record_ids` 中，跳过该结果。
- 如果动态检索结果可构造出的 `slot_value` key 出现在 `rendered_dedupe_keys` 中，跳过该结果。
- 如果动态结果渲染后的 canonical bullet 出现在 `rendered_canonical_bullets` 中，跳过该结果。
- 只对自动注入路径应用上述过滤；`memory_search` 工具仍可显式返回这些记录，因为工具搜索是用户/agent 主动查询，不是 prompt 自动注入。

这保证 resident memory 与 dynamic retrieved memory 不会在同一轮 system prompt 中重复表达同一事实，同时不影响显式深查能力。

## 12. 数据目录影响

Install flow overhaul 保持 `SEBASTIAN_DATA_DIR` 指向 root，并新增 `settings.user_data_dir` 表达用户拥有的数据：

```text
settings.data_dir       -> ~/.sebastian
settings.user_data_dir  -> ~/.sebastian/data
settings.logs_dir       -> ~/.sebastian/logs
settings.run_dir        -> ~/.sebastian/run
```

Resident snapshot 文件必须放在 `settings.user_data_dir / "memory"` 下，而不是 `settings.data_dir / "memory"`。这样快照与数据库、secret key、workspace、extensions 同属用户数据域，不会混进 app/log/run 关注点。

## 13. 测试

单元测试：

- Snapshot builder 包含 allowlisted 且 `confidence >= 0.8` 的记录。
- Snapshot builder 排除低于 `0.8` 的记录。
- Snapshot builder 排除 `sensitive`、`needs_review`、`do_not_auto_inject`。
- Snapshot builder 排除 inactive、expired、future-dated records。
- Allowlist 外的 pinned records 在通过公共过滤和 pinned eligibility contract 后进入 `Pinned Notes`。
- Pinned records 仍受 confidence 和 policy filters 约束。
- Renderer 会省略空 subsection 和整体空 section。
- Renderer 对 resident 内部重复做去重：同 record id、同标准化 bullet、同 `slot_value` key 都只保留一条。
- 同一记录同时满足 allowlist 与 pinned 时只进入 `Core Profile`。
- Metadata 的 `rendered_record_ids` / `rendered_dedupe_keys` / `rendered_canonical_bullets` 与最终 Markdown 内容一致。
- `slot_value` key 使用稳定 canonical JSON + SHA-256 生成。
- Resident 内部去重按全局候选顺序保留第一条：Core Profile 候选优先，然后才是 allowlist 外 Pinned 候选。
- Snapshot 路径是 `settings.user_data_dir / "memory"`。
- 快照文件缺失或不可读时，reader 返回空字符串。
- 原子写入会写 Markdown 与 metadata。
- 已提交的 status、policy tag、confidence、validity、content update 或 delete 后，`mark_dirty()` 会阻止 reader 继续提供旧的不合格内容。
- Dirty 后 rebuild 失败会留下 `snapshot_state = "error"` 和空 Markdown 文件。
- Metadata mismatch 会确定性返回空并调度 rebuild。
- 部分原子写入或崩溃后，只能留下旧的 `ready` snapshot 或空的 non-ready snapshot；绝不能留下会被当作 ready 提供的 Markdown/metadata 混合状态。
- Markdown 替换后、metadata 替换前崩溃时，因为 `markdown_hash` 不匹配，所以不会提供内容。
- 已提交且影响 resident eligibility 的 mutation 与 prompt assembly 并发时，写 API 不得在 `mark_dirty()` 让 resident reader 返回空之前报告成功。
- Resident reads 会等待任何处在 DB commit 与 `mark_dirty()` 之间的 writer。
- In-flight rebuild 不能在后续 dirty generation 之后发布 stale `ready` metadata。

BaseAgent 测试：

- Prompt 顺序是 base system prompt → resident memory → dynamic retrieved memory → todos。
- 现有 `_memory_section()` 测试保留，但命名/描述应调整为 dynamic retrieval tests。
- Dynamic retrieval 返回空不等于 resident memory 为空。
- Prompt assembly 在热路径读取 resident Markdown 时不访问 SQLite。
- Dynamic retrieval 自动注入会过滤已在 resident snapshot 中出现的 record id / `slot_value` key / canonical bullet。
- `memory_search` 工具不受 resident 去重过滤影响，仍可显式返回相关记录。

集成测试：

- Gateway startup 在数据目录初始化后重建 resident snapshot。
- 记忆写入后 dirty refresh 在 DB transaction 外更新 snapshot。

## 14. 延后工作

- `memory_pin` / `memory_unpin` owner-only 管理 API。
- Android 或 Web UI，用于 pin、unpin、review 被跳过的 pinned records。
- Cross-session consolidation 产生自动 pin 建议。
- Owner 可手动编辑的 resident notes 文件。
- Sensitive memory 脱敏与按策略注入。
- 兼容面审查后，将 `_memory_section()` 重命名为 `_dynamic_memory_section()`。

## 15. 验收标准

- 每个 Sebastian depth-1 turn 都可以在不查询 SQLite 的情况下包含 resident memory。
- Resident memory 来自 `settings.user_data_dir` 下可重建的快照。
- 只有高置信 allowlisted profile records 和通过严格过滤的 pinned records 进入 resident snapshot。
- Dynamic retrieval 继续可用，并清楚记录为本轮相关召回。
- 本阶段不引入新的 pin 创建工作流。
