import asyncio
from collections.abc import Awaitable, Callable

import httpx

from app.domain.exceptions import NotificationDeliveryError
from app.domain.models import Notification
from app.infrastructure.http_retry import retry_policy
from app.infrastructure.notifications.rate_limiter import SlidingWindowRateLimiter


class HttpNotificationSender:
    """NotificationSender adapter for the provider (/v1/notify).

    Every attempt (including retries) first takes a slot from the rate limiter,
    so we stay under the provider limit instead of fighting it with 429s.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        rate_limiter: SlidingWindowRateLimiter,
        retry_attempts: int = 4,
        retry_initial_wait: float = 0.5,
        retry_max_wait: float = 5.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._rate_limiter = rate_limiter
        self._retry = lambda: retry_policy(retry_attempts, retry_initial_wait, retry_max_wait, sleep)

    async def send(self, notification: Notification) -> None:
        payload = {"to": notification.to, "message": notification.message, "type": notification.channel.value}
        try:
            async for attempt in self._retry():
                with attempt:
                    await self._rate_limiter.acquire()
                    response = await self._client.post("/v1/notify", json=payload)
                    response.raise_for_status()
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            reason = "notify_unavailable" if status == 429 or status >= 500 else "notify_rejected"
            raise NotificationDeliveryError(reason, f"provider answered {status}") from error
        except httpx.HTTPError as error:
            raise NotificationDeliveryError("notify_unavailable", type(error).__name__) from error
