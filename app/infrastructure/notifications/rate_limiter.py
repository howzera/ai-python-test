import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable


class SlidingWindowRateLimiter:
    """Allows at most `max_calls` in any window of `period` seconds; extra callers wait.

    Callers are served in arrival order because they queue on the lock.
    """

    def __init__(
        self,
        max_calls: int,
        period: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._max_calls = max_calls
        self._period = period
        self._clock = clock
        self._sleep = sleep
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = self._clock()
                while self._calls and now - self._calls[0] >= self._period:
                    self._calls.popleft()
                if len(self._calls) < self._max_calls:
                    self._calls.append(now)
                    return
                # Wait until the oldest call leaves the window.
                await self._sleep(self._period - (now - self._calls[0]))
