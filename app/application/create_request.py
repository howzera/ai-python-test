from app.domain.models import NotificationRequest
from app.domain.ports import RequestRepository


class CreateNotificationRequest:
    """Use case: register a new request in 'queued' status. Nothing is sent yet."""

    def __init__(self, repository: RequestRepository) -> None:
        self._repository = repository

    async def execute(self, user_input: str) -> NotificationRequest:
        request = NotificationRequest(user_input=user_input)
        await self._repository.add(request)
        return request
