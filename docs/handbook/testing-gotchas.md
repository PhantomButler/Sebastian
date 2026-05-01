# 测试坑点手册

收录本项目在编写和维护测试过程中反复踩到的坑，每条均给出根因和规则，避免重复踩雷。

---

## 1. Python mock：patch 路径打在使用方，不是定义方

**根因**：`from module import func` 把 `func` 绑定到当前模块的命名空间。
`patch("module.func")` 只改定义模块里的引用，已经绑定到其他模块的引用不受影响。

**规则 — patch 路径必须是目标代码实际查找函数的位置**：

```python
# ❌ 打在定义方，不会拦截已用 from-import 绑定的调用方
with patch("sebastian.memory.retrieval.retrieve_memory_section", ...):
    ...

# ✅ 打在使用方（MemoryRetrievalService 的模块），才能正确拦截
with patch("sebastian.memory.services.retrieval.retrieve_memory_section", ...):
    ...
```

**判断规则**：在目标模块里看 import 方式：
- `import module` → 调用方写 `module.func()`，patch `module.func` 即可。
- `from module import func` → 调用方写 `func()`，必须 patch `calling_module.func`。

---

## 2. aiosqlite 测试清理规范（Linux CI 关键）

**根因**：aiosqlite 每个连接跑一个 worker 线程，`engine.dispose()` 只发送 close 信号，不等线程真正退出；Linux 上 function-scoped event loop 关闭时若线程未退出会挂住下一个 loop。

**规则 1 — async fixture 中 dispose engine 后必须加 `sleep(0)`**：

```python
@pytest.fixture
async def sqlite_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    ...
    try:
        yield factory
    finally:
        await engine.dispose()
        await asyncio.sleep(0)  # 让 aiosqlite worker 线程完成最后一次回调后退出
```

**规则 2 — `asyncio.run()` 内部的临时 engine 必须在 loop 关闭前 dispose**：

```python
async def _seed() -> None:
    await init_db()
    ...
    # 必须在 asyncio.run() 关闭 loop 前 dispose，否则 worker 线程无法回调
    from sebastian.store.database import get_engine
    await get_engine().dispose()
    await asyncio.sleep(0)

asyncio.run(_seed())
# dispose 后立即重置全局引用，让下一个 context（如 TestClient）用新引擎
db_module._engine = None
db_module._session_factory = None
```

**规则 3 — gateway lifespan 关闭时 dispose engine**：

```python
# lifespan teardown（yield 之后）
await get_engine().dispose()
```

确保 TestClient 退出时 worker loop 中的 aiosqlite 线程也能干净退出。

**规则 4 — 不要在 async 测试中使用 `asyncio.create_subprocess_exec`**：

Linux 上该调用注册 `PidfdChildWatcher`，function-scoped event loop 关闭时 watcher cleanup 会挂住。改用 `asyncio.to_thread(subprocess.run, ...)` 代替。

---

## 3. Android ViewModel 协程测试规范（避免挂起）

**根因**：ChatViewModel 等 ViewModel 的 `init` 块会启动含 `while(true) { delay(N) ... }` 的无限后台协程（如 `startDeltaFlusher`）。在单元测试中调用 `dispatcher.scheduler.advanceUntilIdle()` 时，该循环每次 delay 结束后又立刻调度下一个 delay，队列永远不为空，导致 `advanceUntilIdle()` 死循环，测试永远挂起（Gradle 停在 97% EXECUTING，只完成了 1 个 test）。

**规则 1 — 禁止在 ViewModel 测试体内调用 `advanceUntilIdle()`**：

```kotlin
// ❌ 会死循环，测试永远挂起
viewModel.refreshInputCapabilities(null)
dispatcher.scheduler.advanceUntilIdle()

// ✅ 只执行当前时间点已排队的任务，不推进虚拟时间
viewModel.refreshInputCapabilities(null)
dispatcher.scheduler.runCurrent()
```

**规则 2 — `advanceTimeBy(N)` 可以用（有界），但要注意 N 足够大让目标协程体执行完**：

```kotlin
dispatcher.scheduler.advanceTimeBy(100)  // OK：有界，最多跑几次 flusher 迭代
```

**规则 3 — `runTest` 会在测试体结束后自动调 `advanceUntilIdle()`，因此 `vmTest` 的 `finally { viewModelScope.cancel() }` 必须在 `runTest` 结束前执行**（已有保障，不要把 cancel 移到 `runTest` 外面）。
