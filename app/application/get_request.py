from app.domain.exceptions import RequestNotFoundError
from app.domain.models import NotificationRequest
from app.domain.ports import RequestRepository


class GetNotificationRequest:
    """Use case: read the current status of a request."""

    def __init__(self, repository: RequestRepository) -> None:
        self._repository = repository

    async def execute(self, request_id: str) -> NotificationRequest:
        request = await self._repository.get(request_id)
        if request is None:
            raise RequestNotFoundError(request_id)
        return request
