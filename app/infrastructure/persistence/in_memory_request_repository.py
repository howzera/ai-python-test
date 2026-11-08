from app.domain.models import NotificationRequest


class InMemoryRequestRepository:
    """RequestRepository in a dict. Lost on restart and not shared between replicas:
    fine for this test, Redis or a database in production."""

    def __init__(self) -> None:
        self._requests: dict[str, NotificationRequest] = {}

    async def add(self, request: NotificationRequest) -> None:
        self._requests[request.id] = request

    async def get(self, request_id: str) -> NotificationRequest | None:
        return self._requests.get(request_id)

    async def save(self, request: NotificationRequest) -> None:
        self._requests[request.id] = request
