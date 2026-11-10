import logging

from app.domain.exceptions import ProcessingError, RequestNotFoundError
from app.domain.guardrails import validate_intent
from app.domain.models import NotificationRequest, RequestStatus
from app.domain.ports import IntentExtractor, JobScheduler, NotificationSender, RequestRepository

logger = logging.getLogger(__name__)


class ProcessNotificationRequest:
    """Use case: extract -> validate -> send, in the background.

    `execute` only accepts the work (the API answers 202). Only a 'queued' request
    starts the pipeline, so calling /process twice never calls the AI twice.
    """

    def __init__(
        self,
        repository: RequestRepository,
        extractor: IntentExtractor,
        sender: NotificationSender,
        scheduler: JobScheduler,
    ) -> None:
        self._repository = repository
        self._extractor = extractor
        self._sender = sender
        self._scheduler = scheduler

    async def execute(self, request_id: str) -> NotificationRequest:
        request = await self._repository.get(request_id)
        if request is None:
            raise RequestNotFoundError(request_id)

        # No 'await' between the check and the change: with one event loop, two
        # concurrent calls cannot both see 'queued'. With Redis this would be an atomic SET NX.
        if request.status is RequestStatus.QUEUED:
            request.start_processing()
            await self._repository.save(request)
            self._scheduler.submit(lambda: self._run_pipeline(request_id))
        return request

    async def _run_pipeline(self, request_id: str) -> None:
        request = await self._repository.get(request_id)
        if request is None:
            return
        try:
            intent = await self._extractor.extract(request.user_input)
            notification = validate_intent(intent, request.user_input)
            await self._sender.send(notification)
            request.mark_sent()
            logger.info("request=%s sent channel=%s", request_id, notification.channel)
        except ProcessingError as error:
            request.mark_failed(error.reason)
            logger.warning("request=%s failed reason=%s detail=%s", request_id, error.reason, error.detail)
        except Exception:
            # Any bug must end in 'failed', never leave the request stuck in 'processing'.
            request.mark_failed("internal_error")
            logger.exception("request=%s failed with an unexpected error", request_id)
        await self._repository.save(request)
