"""ADR‑3: one event loop per worker process (app/tasks/_loop.py).

Plain (sync) tests on purpose — Celery tasks call ``run_async`` from sync code.
"""

import asyncio

import pytest

from app.tasks import _loop


@pytest.fixture(autouse=True)
def fresh_loop():
    _loop._loop, _loop._loop_pid = None, None
    yield
    loop = _loop._loop
    if loop is not None and not loop.is_closed():
        loop.close()
    _loop._loop, _loop._loop_pid = None, None
    asyncio.set_event_loop(None)


def test_every_task_in_a_process_shares_one_loop():
    async def current():
        return asyncio.get_running_loop()

    first, second = _loop.run_async(current()), _loop.run_async(current())
    assert first is second is _loop.get_loop()


def test_a_forked_child_gets_its_own_loop(monkeypatch):
    parent = _loop.get_loop()
    monkeypatch.setattr(_loop.os, "getpid", lambda: -1)          # "after fork"
    assert _loop.get_loop() is not parent


def test_exceptions_propagate_and_the_loop_stays_usable():
    async def boom():
        raise ValueError("task failed")

    with pytest.raises(ValueError):
        _loop.run_async(boom())

    async def ok():
        return 42

    assert _loop.run_async(ok()) == 42


def test_an_interrupted_task_is_unwound_before_the_next_one():
    """A soft time limit arrives as an exception raised inside the loop; the
    task's finally blocks must run on its own loop, and nothing may resume later."""
    cleaned = []

    async def long_task():
        try:
            await asyncio.sleep(10)
        finally:
            cleaned.append("rolled back")

    loop = _loop.get_loop()

    def interrupt():
        raise KeyboardInterrupt            # asyncio re-raises this out of run_until_complete

    loop.call_later(0.01, interrupt)
    with pytest.raises(KeyboardInterrupt):
        _loop.run_async(long_task())
    assert cleaned == ["rolled back"]
    assert not [t for t in asyncio.all_tasks(loop) if not t.done()]


def test_fire_and_forget_leftovers_are_cancelled():
    started = []

    async def leaves_a_stray():
        async def stray():
            started.append(True)
            await asyncio.sleep(10)

        asyncio.get_running_loop().create_task(stray())
        await asyncio.sleep(0)
        return "done"

    assert _loop.run_async(leaves_a_stray()) == "done"
    assert started and not [t for t in asyncio.all_tasks(_loop.get_loop()) if not t.done()]
