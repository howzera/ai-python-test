import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class AsyncioJobScheduler:
    """JobScheduler with asyncio tasks in the same process.

    Pending jobs are lost if the process restarts (production: a durable queue).
    """

    def __init__(self) -> None:
        # asyncio keeps only weak references to tasks: we hold them so they are not collected.
        self._tasks: set[asyncio.Task] = set()

    def submit(self, job: Callable[[], Awaitable[None]]) -> None:
        task = asyncio.create_task(job())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @property
    def pending(self) -> int:
        return len(self._tasks)

    async def shutdown(self) -> None:
        if self._tasks:
            logger.warning("cancelling %d pending jobs on shutdown", len(self._tasks))
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
