---
version: "1.0"
last_updated: 2026-05-03
status: implemented
---

# Single-Instance Scheduler

*← [Core 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 背景与范围

Sebastian 需要一类进程内、系统级、周期执行的后台任务，例如：

- `AttachmentStore.cleanup()` 引用计数与过期附件清理
- Memory 未来维护任务：补扫、降权、整理、索引修复、重复压缩
- 后续用户主动触发系统中的 due trigger 扫描入口

第一版只服务单实例自托管部署，因此不引入分布式锁、外部队列、worker 集群、cron UI 或用户可配置 job。Scheduler 不是 Agent Task 队列，也不直接表达提醒/主动消息语义；用户业务触发应由未来 `TriggerDispatcher` 等业务层处理。

---

## 2. 模块边界

实现位于 `sebastian/trigger/`：

```text
trigger/
├── scheduler.py      # ScheduledJob, JobRegistry, SchedulerRunner
├── job_runs.py       # ScheduledJobRunStore：scheduled_job_runs 读写
└── jobs.py           # register_builtin_jobs(...)
```

职责划分：

| 文件 | 职责 |
|------|------|
| `scheduler.py` | 调度循环、时间计算、并发保护、timeout 包裹和 shutdown |
| `job_runs.py` | 运行历史记录与最近成功时间查询；不存 job definition |
| `jobs.py` | 注册项目内置任务，当前只有 `attachments.cleanup` |

`trigger/` 是 Phase 4 主动触发目录；当前 scheduler 只是其中的基础设施子集，覆盖系统内置后台 job。

---

## 3. Job 定义

```python
@dataclass(slots=True)
class ScheduledJob:
    id: str
    handler: Callable[[], Awaitable[Any]]
    interval: timedelta
    run_on_startup: bool = False
    startup_delay: timedelta = timedelta(seconds=30)
    timeout_seconds: float = 300
    concurrency_policy: Literal["skip_if_running"] = "skip_if_running"
```

> **实现增强**：`timeout_seconds` 在代码中为 `float`，允许测试或未来 job 使用小数秒 timeout；语义上仍是秒。

约束：

- `id` 必须稳定，作为 `scheduled_job_runs.job_id`
- 第一版只支持 interval，不支持 cron
- `handler` 不接收 scheduler 内部状态；依赖通过注册时闭包注入
- `handler` 返回值被调度层忽略
- `handler` 必须幂等；失败时抛异常，由 scheduler 统一记录

`JobRegistry.register()` 遇到重复 `job.id` 直接 `raise ValueError`，启动失败比静默覆盖安全。不支持运行时动态增删 job。

---

## 4. SchedulerRunner 流程

### 4.1 Startup

`SchedulerRunner.start()` 遍历所有 job，并通过 `ScheduledJobRunStore.get_last_success_at(job.id)` 推导首次 `next_run_at`：

| 历史状态 | 推导规则 |
|----------|----------|
| 有最近 success | `last_success_at + interval` |
| 推导时间已过期 | `now + startup_delay`，避免重启瞬间集中执行 |
| 无 success 且 `run_on_startup=True` | `now + startup_delay` |
| 无 success 且 `run_on_startup=False` | `now + interval` |

`get_last_success_at()` 使用 `coalesce(finished_at, started_at)`；新 run 必填 `finished_at`，旧数据缺失时回退到 `started_at`。

### 4.2 Loop

主循环按 `poll_interval`（默认 30s）检查 due job：

1. 清理已完成的 `_running` task 引用
2. 若当前时间未到 `next_run_at`，跳过
3. due 时先把 `next_run_at` 设为 `now + interval`
4. 若同一 job 正在运行且策略为 `skip_if_running`，写一条 `skipped` run
5. 否则 `asyncio.create_task(_run_job(job))`

### 4.3 Run

`_run_job(job)`：

1. 写入 `running` run record
2. `asyncio.wait_for(job.handler(), timeout=job.timeout_seconds)`
3. 成功写 `success`
4. `TimeoutError` 写 `timeout`
5. 其他异常写 `failed` 和错误字符串，并记录 exception log
6. shutdown cancel 时写 `cancelled`

任何 job 结果都不会让 scheduler 主循环退出。

### 4.4 Shutdown

`aclose()`：

1. 停止产生新 run
2. cancel 主 loop task
3. 等待正在运行的 job 到 grace period（默认 5s）
4. grace 超时后 cancel pending job task；`_run_job()` 负责写 `cancelled`

Gateway shutdown 顺序要求 scheduler 在 DB engine dispose 前关闭。

---

## 5. 运行历史表

ORM model：`sebastian/store/models.py::ScheduledJobRunRecord`

```python
class ScheduledJobRunRecord(Base):
    __tablename__ = "scheduled_job_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    started_at: Mapped[datetime] = mapped_column(_UTCDateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(_UTCDateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
```

索引：`ix_scheduled_job_runs_job_status_started(job_id, status, started_at)`。

| status | 含义 |
|--------|------|
| `running` | run 已开始但尚未结束 |
| `success` | handler 正常完成 |
| `failed` | handler 抛出非 timeout 异常 |
| `timeout` | handler 超过 `timeout_seconds` |
| `skipped` | 触发时发现同 job 正在运行，按 `skip_if_running` 跳过 |
| `cancelled` | shutdown grace 超时后取消 |

`ScheduledJobRunStore` 提供：

- `start_run(job_id, started_at) -> run_id`
- `finish_run(run_id, status, finished_at, *, duration_ms=None, error=None) -> None`
- `record_skipped(job_id, at, reason) -> None`
- `get_last_success_at(job_id) -> datetime | None`

`record_skipped()` 写完整 run record：`started_at = finished_at = at`，`duration_ms = 0`，`error = reason`。

---

## 6. 内置任务

当前唯一内置 job：`attachments.cleanup`

```python
def register_builtin_jobs(registry: JobRegistry, *, attachment_store: AttachmentStore) -> None:
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

- `AttachmentStore.cleanup()` 已经是幂等引用计数清理
- `run_on_startup=True` 可补偿服务关闭期间错过的清理
- startup delay 避免与 DB 初始化、memory bootstrap、agent registry 初始化竞争资源
- interval 6 小时；实际 TTL 仍由 attachment store 内部策略控制

---

## 7. Gateway 集成

`sebastian/gateway/app.py` lifespan startup：

```text
DB init
→ memory storage/bootstrap
→ AttachmentStore
→ JobRegistry + register_builtin_jobs(...)
→ SchedulerRunner(...).start()
→ state.scheduler = scheduler
→ agent/runtime startup
```

shutdown：

```text
state.scheduler.aclose()
→ completion_notifier.aclose()
→ memory schedulers/refresher close
→ DB engine dispose
```

`state.scheduler` 只保存 runtime 引用，当前没有对外 debug API。

---

## 8. 不变量

- 第一版是单实例进程内调度，不保证多进程/多副本只执行一次
- Job definition 的真实来源是代码，不是数据库
- `scheduled_job_runs` 是运行历史和重启恢复依据，不是调度配置表
- 同一进程内同一 `job_id` 最多一个 running handler
- 历史 `running` 行不是锁；进程重启后不用于阻止新 run
- Job handler 必须幂等；scheduler 只负责调度和记录，不负责业务回滚
- Scheduler 不解析用户提醒内容，不直接生成用户消息

---

*← [Core 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
