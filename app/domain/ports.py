from collections.abc import Awaitable, Callable
from typing import Protocol

from app.domain.models import ExtractedIntent, Notification, NotificationRequest


class RequestRepository(Protocol):
    """Output port: where requests are stored (memory today, Redis or a database tomorrow)."""

    async def add(self, request: NotificationRequest) -> None: ...

    async def get(self, request_id: str) -> NotificationRequest | None: ...

    async def save(self, request: NotificationRequest) -> None: ...


class IntentExtractor(Protocol):
    """Output port: turns free text into an ExtractedIntent.

    Raises AiRefusalError, UnparseableAiResponseError or AiUnavailableError.
    """

    async def extract(self, user_input: str) -> ExtractedIntent: ...


class NotificationSender(Protocol):
    """Output port: delivers a validated notification. Raises NotificationDeliveryError."""

    async def send(self, notification: Notification) -> None: ...


class JobScheduler(Protocol):
    """Output port: runs work after the HTTP response (asyncio tasks today, a queue tomorrow)."""

    def submit(self, job: Callable[[], Awaitable[None]]) -> None: ...
