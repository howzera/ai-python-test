import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from app.domain.exceptions import InvalidStatusTransitionError


class RequestStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"


class Channel(StrEnum):
    EMAIL = "email"
    SMS = "sms"


@dataclass(frozen=True)
class ExtractedIntent:
    """What the AI understood, after fixing the format but BEFORE business validation.

    Any field can be None: the AI may omit it. The guardrails decide if it is usable.
    """

    to: str | None
    message: str | None
    type: str | None


@dataclass(frozen=True)
class Notification:
    """A validated notification, safe to send."""

    to: str
    message: str
    channel: Channel


@dataclass
class NotificationRequest:
    """One user request and its lifecycle: queued -> processing -> sent | failed."""

    user_input: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: RequestStatus = RequestStatus.QUEUED
    failure_reason: str | None = None

    def start_processing(self) -> None:
        self._transition(RequestStatus.QUEUED, RequestStatus.PROCESSING)

    def mark_sent(self) -> None:
        self._transition(RequestStatus.PROCESSING, RequestStatus.SENT)

    def mark_failed(self, reason: str) -> None:
        self._transition(RequestStatus.PROCESSING, RequestStatus.FAILED)
        self.failure_reason = reason

    def _transition(self, expected: RequestStatus, new: RequestStatus) -> None:
        if self.status is not expected:
            raise InvalidStatusTransitionError(self.id, self.status, new)
        self.status = new
