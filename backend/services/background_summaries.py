"""CSA-30: run `summarize_node` in the background, after the response is returned.

`BackgroundSummaries` lives on `app.state.summaries` (created in main.py's lifespan) and holds:
- one `asyncio.Lock` per LangGraph thread. Every `graph.ainvoke` of the customer-support graph runs under its thread's
  lock (see `_locked_ainvoke` in customer_support_service.py), so the next request on a thread waits for an unfinished
  background summary instead of writing the checkpoint concurrently (LangGraph does not lock threads).
- strong references to the background summary tasks (asyncio keeps only weak ones), so `drain()` can wait for them
  on shutdown, before the checkpointer/ store and LangFuse are closed.

An in-process lock is enough because the app runs as a single uvicorn process (the Dockerfile has no `--workers`);
revisit (e.g. a Redis lock) if workers are ever added.
It must be an `asyncio.Lock`: a `threading.Lock` waiting inside a coroutine would block the whole event loop.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)


class _ThreadLock:
    __slots__ = ("lock", "users")

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.users = 0  # holders + waiters; the entry is dropped when it reaches 0 so the dict doesn't grow forever


class BackgroundSummaries:
    def __init__(self) -> None:
        self._locks: dict[str, _ThreadLock] = {}
        self._tasks: set[asyncio.Task] = set()

    @asynccontextmanager
    async def thread_lock(self, thread_id: str) -> AsyncGenerator[None, None]:
        """Hold the lock of `thread_id` for the `async with` block. Waiting suspends this coroutine only;
        other threads (customers) have their own locks and never wait on each other."""
        # returns the value of a specified key if it exists; if the key is missing, 
        # it inserts the key with the given default value and returns that new value.
        entry = self._locks.setdefault(thread_id, _ThreadLock())
        entry.users += 1
        try:
            # This is where it locks. It does not lock the whole thread_lock. It does allow other invocation of the same thread 
            # enter up to this point, and increment the user count.
            async with entry.lock:
                yield
        finally:
            # No await between the decrement and the delete, so no other coroutine can grab the entry in between.
            entry.users -= 1
            if entry.users == 0:
                del self._locks[thread_id]

    def schedule(self, coro: Coroutine[Any, Any, None]) -> None:
        """Run `coro` as a background task. The coroutine handles (logs) its own errors."""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        # registers a synchronous function to run automatically as soon as the task finishes, removing it from the set of pending tasks.
        task.add_done_callback(self._tasks.discard) 

    # A getter function to retrieve the number of pending background summary tasks.
    @property
    def pending(self) -> int:
        return len(self._tasks)

    async def drain(self, timeout: float | None = None) -> None:
        """Wait for the pending background summaries (on shutdown, and in tests). Tasks still running
        after `timeout` are left alone and logged; their summary is redone by the next trigger or Exit."""
        if not self._tasks:
            return
        # Wait for all pending background summary tasks to complete, up to the specified timeout.
        # `asyncio.wait` returns a tuple of (done, pending) sets of tasks.
        _, still_running = await asyncio.wait(set(self._tasks), timeout=timeout)
        if still_running:
            logger.warning("%d background summary task(s) still running after %ss", len(still_running), timeout)
