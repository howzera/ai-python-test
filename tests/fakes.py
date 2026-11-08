from collections.abc import Awaitable, Callable

from app.domain.exceptions import NotificationDeliveryError
from app.domain.models import ExtractedIntent, Notification


class FakeClock:
    """Controllable time source: tests time-based code without real waits."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeExtractor:
    """IntentExtractor that returns a fixed intent or raises a fixed error."""

    def __init__(self, intent: ExtractedIntent | None = None, error: Exception | None = None) -> None:
        self.intent = intent
        self.error = error
        self.calls: list[str] = []

    async def extract(self, user_input: str) -> ExtractedIntent:
        self.calls.append(user_input)
        if self.error:
            raise self.error
        assert self.intent is not None
        return self.intent


class FakeSender:
    """NotificationSender that records what it sends, or fails."""

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.sent: list[Notification] = []
        self.fail_with = fail_with

    async def send(self, notification: Notification) -> None:
        if self.fail_with:
            raise self.fail_with
        self.sent.append(notification)


class ManualScheduler:
    """JobScheduler that keeps the jobs until the test runs them."""

    def __init__(self) -> None:
        self.jobs: list[Callable[[], Awaitable[None]]] = []

    def submit(self, job: Callable[[], Awaitable[None]]) -> None:
        self.jobs.append(job)

    async def run_all(self) -> None:
        jobs, self.jobs = self.jobs, []
        for job in jobs:
            await job()


def delivery_error() -> NotificationDeliveryError:
    return NotificationDeliveryError("notify_unavailable")
