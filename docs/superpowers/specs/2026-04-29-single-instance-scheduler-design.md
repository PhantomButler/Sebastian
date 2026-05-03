---
date: 2026-04-29
status: draft
topic: single-instance-scheduler
integrated_to: core/single-instance-scheduler.md
integrated_at: 2026-05-03
---

# Single-Instance Scheduler

## 1. 背景

Sebastian 现在已经出现需要后台周期执行的系统任务：

1. `AttachmentStore.cleanup()` 已具备引用计数清理语义，但还没有调用方。
2. Memory 已有会话结束后的沉淀链路，后续还会需要周期性维护：补扫、降权、整理、索引修复、重复压缩等。
3. 未来会有用户可见的主动触发能力，例如“到某个时间点主动通知用户/发消息”。

这些任务都和时间有关，但不是同一层语义：

- **系统后台维护任务**：清理附件、维护记忆、补扫索引。它们应幂等、可重复执行、失败只影响自身。
- **用户业务触发**：提醒、定时主动发消息。它们需要独立的数据模型和业务分发逻辑。
- **Agent 执行任务**：真正唤起 Sebastian / Sub-Agent 的工作单元。

第一版只服务单实例自托管，因此不做分布式锁、外部队列、worker 集群和用户可配置调度 UI。

## 2. 范围

### P0 范围

- 在 `sebastian/trigger/` 引入单实例进程内 async scheduler。
- 支持代码内置 job definition，不把 job definition 持久化到 DB。
- 新增 `scheduled_job_runs` 运行历史表，记录每次执行、跳过、失败和超时。
- 启动时基于 `scheduled_job_runs` 最近一次成功运行记录推导 `next_run_at`，避免重启后所有 interval 从零开始。
- 接入第一批内置 job：`attachments.cleanup`。
- Gateway lifespan startup 启动 scheduler，shutdown 优雅停止。
- Job 默认并发策略为 `skip_if_running`，同一个 job 上一次未结束时下一次触发只记录 `skipped`，不并发执行。

### 不做

- 不做多实例互斥、leader election、DB advisory lock 或分布式锁。
- 不引入 Celery / RQ / 外部队列。
- 不做用户可配置 cron、interval、enable/disable UI。
- 不持久化 job definition 到 `scheduled_jobs` 表。
- 不实现提醒/主动消息的数据模型和 API，只在边界上预留未来扫描入口。
- 不把 scheduler 设计成 Agent Task 队列。

## 3. 总体设计

### 3.1 模块边界

新增/扩展 `sebastian/trigger/`：

```text
trigger/
├── __init__.py
├── scheduler.py      # ScheduledJob, JobRegistry, SchedulerRunner
├── job_runs.py       # ScheduledJobRunStore：scheduled_job_runs 读写
└── jobs.py           # register_builtin_jobs(...)
```

职责划分：

- `scheduler.py` 只负责调度循环、时间计算、并发保护、timeout 包裹和 shutdown。
- `job_runs.py` 只负责运行历史记录和最近成功时间查询，不存 job definition。
- `jobs.py` 负责把项目中的内置任务注册进 registry，第一版只注册 `attachments.cleanup`。

`trigger/` 是已有 Phase 4 主动触发占位目录。第一版 scheduler 是它的基础设施子集，但只覆盖系统内置后台 job。

### 3.2 ScheduledJob

```python
@dataclass(slots=True)
class ScheduledJob:
    id: str
    handler: Callable[[], Awaitable[Any]]
    interval: timedelta
    run_on_startup: bool = False
    startup_delay: timedelta = timedelta(seconds=30)
    timeout_seconds: int = 300
    concurrency_policy: Literal["skip_if_running"] = "skip_if_running"
```

约束：

- `id` 必须稳定，作为 `scheduled_job_runs.job_id`。
- 第一版只支持 `interval`，不支持 cron。
- `handler` 不接收 scheduler 内部状态；需要的 store/registry 在注册时闭包注入。
- `handler` 的返回值会被 scheduler 忽略；例如 `AttachmentStore.cleanup()` 返回清理数量，但调度层只关心成功/失败。
- `handler` 必须幂等，失败时抛异常，由 scheduler 统一记录。

### 3.3 JobRegistry

`JobRegistry` 是进程内容器：

```python
class JobRegistry:
    def register(self, job: ScheduledJob) -> None: ...
    def list_jobs(self) -> list[ScheduledJob]: ...
```

规则：

- 重复 `job.id` 直接 `raise ValueError`，启动失败比静默覆盖安全。
- 不支持运行时动态增删 job。
- 不读取 DB 中的 job definition。

### 3.4 SchedulerRunner

`SchedulerRunner` 管理所有内置 job：

1. startup：
   - 遍历 registry 中所有 job；
   - 调 `ScheduledJobRunStore.get_last_success_at(job.id)`；
   - 若有最近成功时间：`next_run_at = last_success_at + job.interval`；
   - 若推导出的 `next_run_at <= now`：`next_run_at = now + job.startup_delay`，避免服务长时间关闭后重启瞬间所有过期 job 同时执行；
   - 若没有成功记录且 `run_on_startup=True`：`next_run_at = now + startup_delay`；
   - 若没有成功记录且 `run_on_startup=False`：`next_run_at = now + job.interval`。
2. loop：
   - 定期检查 due job；
   - due 时若同 job 正在运行：写一条 `skipped` run，`next_run_at = now + interval`；
   - 否则创建 task 执行 `_run_job(job)`。
3. `_run_job(job)`：
   - 写入 run start；
   - `asyncio.wait_for(job.handler(), timeout=job.timeout_seconds)`；
   - 成功写 `success`；
   - `TimeoutError` 写 `timeout`；
   - 其他异常写 `failed` 和 error string；
   - 任何结果都不会让 scheduler 主循环退出。
4. shutdown：
   - 停止产生新 run；
   - 等待正在运行的 job 完成到短暂 grace period；
   - grace 超时后 cancel pending job task；
   - 对被 cancel 的 run 写 `failed` 或 `cancelled`。

第一版主 loop 可以使用 `asyncio.create_task` + `asyncio.sleep`，无需 APScheduler。interval 需求简单，少一个依赖更可控。

主循环轮询间隔默认 `poll_interval = timedelta(seconds=30)`，作为 `SchedulerRunner` 构造参数注入，测试可使用更短间隔或 fake clock 直接驱动 due 检查。

## 4. 运行历史表

新增 ORM model：

```python
class ScheduledJobRunRecord(Base):
    __tablename__ = "scheduled_job_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
```

索引：

- `Index("ix_scheduled_job_runs_job_status_started", "job_id", "status", "started_at")`

`status` 取值：

| status | 含义 |
|---|---|
| `running` | run 已开始但尚未结束 |
| `success` | handler 正常完成 |
| `failed` | handler 抛出非 timeout 异常 |
| `timeout` | handler 超过 `timeout_seconds` |
| `skipped` | 触发时发现同 job 正在运行，按 `skip_if_running` 跳过 |
| `cancelled` | shutdown grace 超时后取消 |

`ScheduledJobRunStore` 提供：

- `start_run(job_id, started_at) -> run_id`
- `finish_run(run_id, status, finished_at, error=None) -> None`
- `record_skipped(job_id, at, reason) -> None`
- `get_last_success_at(job_id) -> datetime | None`

重启推导 `next_run_at` 使用最近一次 `success.finished_at`。若历史行缺 `finished_at`，可 fallback 到 `started_at`；新写入必须填 `finished_at`。

`record_skipped(...)` 写完整 run record：

- `started_at = at`
- `finished_at = at`
- `duration_ms = 0`
- `status = "skipped"`
- `error = reason`

## 5. 第一批内置任务

### 5.1 `attachments.cleanup`

注册位置：`sebastian/trigger/jobs.py`

```python
def register_builtin_jobs(
    registry: JobRegistry,
    *,
    attachment_store: AttachmentStore,
) -> None:
    registry.register(
        ScheduledJob(
            id="attachments.cleanup",
            handler=attachment_store.cleanup,
            interval=timedelta(hours=6),
            run_on_startup=True,
            startup_delay=timedelta(minutes=2),
            timeout_seconds=300,
        )
    )
```

设计理由：

- cleanup 已经是幂等引用计数清理，适合作为第一个周期任务。
- `run_on_startup=True` 可以补偿服务关闭期间错过的清理。
- startup 延迟避免和 DB 初始化、memory bootstrap、agent registry 初始化竞争启动资源。
- interval 先定 6 小时；实际 TTL 仍由 `AttachmentStore.cleanup()` 内部 `_UPLOADED_TTL` / `_ORPHAN_TTL` 控制。附件过期窗口是 24 小时，6 小时粒度能把额外滞留控制在可接受范围内，同时避免无意义的高频磁盘/DB 扫描。

## 6. Gateway Lifespan 集成

在 `sebastian/gateway/app.py`：

1. DB 初始化和 store 创建完成后，创建 `JobRegistry`。
2. 调用 `register_builtin_jobs(registry, attachment_store=attachment_store)`。
3. 创建 `SchedulerRunner(registry=registry, run_store=ScheduledJobRunStore(db_factory))`。
4. `await scheduler.start()`。
5. 将 scheduler 存入 `sebastian.gateway.state.scheduler`，方便 debug 路由未来读取。
6. shutdown 时在 DB engine dispose 前 `await scheduler.aclose()`。

初始化顺序约束：

```text
DB init -> stores -> scheduler registry -> scheduler start -> agent/runtime -> yield
shutdown: scheduler close -> memory schedulers close -> engine dispose
```

如果未来某个 job 依赖 agent/runtime，应在 agent/runtime 创建后注册；第一版 `attachments.cleanup` 只依赖 `AttachmentStore`，可以较早启动，但为了降低启动期噪音，实际执行仍有 `startup_delay`。

## 7. 错误处理与可观测性

- Job handler 抛异常时，只影响当前 run；scheduler loop 继续运行。
- 每次 success / failed / timeout / skipped / cancelled 都写 `scheduled_job_runs`。
- error 字段保存简短错误字符串；完整 traceback 走 `logger.exception(...)` 写 main log。
- 单个 job 正在运行时再次 due，写 `skipped`，不静默跳过。
- `timeout` 后不假设 handler 内部状态已回滚；handler 自身必须保证幂等。
- Scheduler 启动时发现注册失败（重复 id）应 fail fast，避免同名 job 不可预测。
- 进程崩溃可能留下 `status="running"` 的孤儿行。`running.started_at + timeout_seconds < now` 可视为 stale；它不影响 `get_last_success_at`，因为重启恢复只查询 `status="success"`。第一版不自动清理 stale running 行，后续可通过维护任务或 debug/运维工具处理。

## 8. 未来用户提醒边界

第一版不实现用户提醒，但预留清晰接缝：

- 未来新增业务表，例如 `user_triggers` / `reminders`，存储用户创建的提醒、到期时间、状态和 payload。
- Scheduler 只注册一个内置扫描 job，例如 `user_triggers.scan_due`。
- `user_triggers.scan_due` 读取 due triggers 后交给业务层 `TriggerDispatcher`。
- `TriggerDispatcher` 决定是发送本地通知、写 session item、创建新 session，还是唤起 Sebastian。
- Scheduler 不解析提醒内容，不直接生成用户消息，不承担权限/通知/对话语义。

这样 scheduler 保持基础设施边界，主动触发系统可以在后续 spec 中独立设计。

## 9. 数据迁移

新增 `ScheduledJobRunRecord` 后：

- 新数据库由 `Base.metadata.create_all` 创建表。
- 现有数据库无需数据迁移；表不存在时 create_all 会创建。
- 不需要 `_apply_idempotent_migrations` 添加列，因为这是新表，不是旧表加字段。

若后续要新增 run 字段，再按现有 `database.py` 幂等 patch 模式处理。

## 10. 测试策略

### 单元测试

- `JobRegistry.register` 拒绝重复 job id。
- 首次启动无历史且 `run_on_startup=True` 时，`next_run_at = now + startup_delay`。
- 首次启动无历史且 `run_on_startup=False` 时，`next_run_at = now + interval`。
- 有最近 success run 时，`next_run_at = last_success.finished_at + interval`。
- 最近 success 推导出的 `next_run_at <= now` 时，使用 `now + startup_delay`，避免重启瞬间集中执行。
- running job 再次 due 时记录 `skipped`，handler 不并发执行。
- handler 成功时写 `success`、`finished_at`、`duration_ms`。
- handler 抛异常时写 `failed` 和 error，并继续调度其他 job。
- handler 超时时写 `timeout`。
- `aclose()` 不再启动新 run，并等待/取消 pending job。

### Store 测试

- `ScheduledJobRunStore.start_run` 写入 `running`。
- `finish_run` 更新状态、结束时间和 duration。
- `record_skipped` 写完整 skipped run。
- `get_last_success_at` 只读取 `status="success"`，忽略 failed/timeout/skipped。
- 多条 success 时取最近的 `finished_at`。
- stale `running` 行不影响最近成功时间查询。

### 集成测试

- Gateway lifespan 启动后注册 `attachments.cleanup`。
- 使用短 interval / fake clock 或直接驱动 runner，验证 cleanup 被调用。
- scheduler shutdown 在 DB engine dispose 前完成，不留下 aiosqlite 线程挂起。
- attachment cleanup 失败时 gateway 仍可处理普通请求，run history 记录 failed。

## 11. 文件改动清单

| 文件 | 改动 |
|---|---|
| `sebastian/trigger/scheduler.py` | 新增 `ScheduledJob` / `JobRegistry` / `SchedulerRunner` |
| `sebastian/trigger/job_runs.py` | 新增运行历史 store |
| `sebastian/trigger/jobs.py` | 注册内置 job，第一版只有 `attachments.cleanup` |
| `sebastian/store/models.py` | 新增 `ScheduledJobRunRecord` |
| `sebastian/gateway/state.py` | 新增 scheduler runtime 引用 |
| `sebastian/gateway/app.py` | lifespan 创建/启动/关闭 scheduler |
| `sebastian/trigger/README.md` | 更新目录与设计边界 |
| `sebastian/store/README.md` | 同步 `scheduled_job_runs` 表说明 |
| `tests/unit/trigger/` | scheduler 和 job run store 单元测试 |
| `tests/integration/` | gateway lifespan + attachment cleanup 集成测试 |

## 12. 不变量

- 第一版部署模型是单实例自托管；不保证多进程/多副本下只执行一次。
- Job definition 的真实来源是代码，不是数据库。
- `scheduled_job_runs` 是运行历史和重启恢复依据，不是调度配置表。
- 同一 `job_id` 在一个进程内最多有一个 running handler。
- 历史 `running` 行不是锁；进程重启后不用于阻止新 run。
- Job handler 必须幂等；scheduler 只负责调度和记录，不负责业务回滚。
- Scheduler shutdown 必须发生在 DB engine dispose 之前。
- Scheduler 不直接表达用户提醒语义；用户触发由未来 `TriggerDispatcher` 负责。
