import asyncio
from collections.abc import Awaitable, Callable

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter


def is_retryable(error: BaseException) -> bool:
    """Temporary failures: network errors, timeouts, 429 (rate limit) and 5xx.

    Other 4xx (401, 422...) are our fault: retrying would fail again.
    """
    if isinstance(error, httpx.TransportError):  # includes every timeout
        return True
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        return status == 429 or status >= 500
    return False


def retry_policy(
    attempts: int,
    initial_wait: float,
    max_wait: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncRetrying:
    """Exponential backoff with jitter (0.5 s, 1 s, 2 s... + random), so that many
    clients that failed together do not retry together."""
    return AsyncRetrying(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential_jitter(initial=initial_wait, max=max_wait),
        retry=retry_if_exception(is_retryable),
        sleep=sleep,
        reraise=True,
    )
