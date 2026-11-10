from app.domain.models import NotificationRequest


class InMemoryRequestRepository:
    """RequestRepository backed by a dict (not persistent, not shared between replicas)."""

    def __init__(self) -> None:
        self._requests: dict[str, NotificationRequest] = {}

    async def add(self, request: NotificationRequest) -> None:
        self._requests[request.id] = request

    async def get(self, request_id: str) -> NotificationRequest | None:
        return self._requests.get(request_id)

    async def save(self, request: NotificationRequest) -> None:
        self._requests[request.id] = request
