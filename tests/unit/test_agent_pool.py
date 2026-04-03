from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_acquire_idle_worker_returns_stock_01_and_marks_busy() -> None:
    from sebastian.core.agent_pool import AgentPool, WorkerStatus

    pool = AgentPool("stock")

    worker_id = await pool.acquire()

    assert worker_id == "stock_01"
    assert pool.status()[worker_id] == WorkerStatus.BUSY


@pytest.mark.asyncio
async def test_release_worker_returns_it_to_idle() -> None:
    from sebastian.core.agent_pool import AgentPool, WorkerStatus

    pool = AgentPool("stock")
    worker_id = await pool.acquire()

    pool.release(worker_id)
    await asyncio.sleep(0)

    assert pool.status()[worker_id] == WorkerStatus.IDLE


@pytest.mark.asyncio
async def test_releasing_non_busy_worker_is_rejected() -> None:
    from sebastian.core.agent_pool import AgentPool

    pool = AgentPool("stock")
    worker_id = await pool.acquire()

    pool.release(worker_id)

    with pytest.raises(ValueError, match=f"Worker {worker_id} is not busy"):
        pool.release(worker_id)


@pytest.mark.asyncio
async def test_all_workers_busy_queues_and_release_wakes_waiter() -> None:
    from sebastian.core.agent_pool import AgentPool, WorkerStatus

    pool = AgentPool("code")
    workers = [await pool.acquire() for _ in range(3)]
    waiter = asyncio.create_task(pool.acquire())

    await asyncio.sleep(0)
    assert pool.queue_depth == 1
    assert not waiter.done()

    pool.release(workers[1])
    next_worker = await waiter

    assert next_worker == workers[1]
    assert pool.status()[next_worker] == WorkerStatus.BUSY
    assert pool.queue_depth == 0


@pytest.mark.asyncio
async def test_double_release_after_handoff_is_rejected() -> None:
    from sebastian.core.agent_pool import AgentPool, WorkerStatus

    pool = AgentPool("code")
    workers = [await pool.acquire() for _ in range(3)]
    first_waiter = asyncio.create_task(pool.acquire())
    second_waiter = asyncio.create_task(pool.acquire())

    await asyncio.sleep(0)

    pool.release(workers[0])
    handed_off_worker = await first_waiter

    assert handed_off_worker == workers[0]
    assert pool.status()[handed_off_worker] == WorkerStatus.BUSY

    pool.release(handed_off_worker)
    second_handoff = await second_waiter

    assert second_handoff == handed_off_worker
    assert pool.status()[handed_off_worker] == WorkerStatus.BUSY


def test_worker_names_are_fixed_order() -> None:
    from sebastian.core.agent_pool import AgentPool

    pool = AgentPool("code")

    assert list(pool.status().keys()) == ["code_01", "code_02", "code_03"]
