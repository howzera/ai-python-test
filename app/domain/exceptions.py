class RequestNotFoundError(Exception):
    def __init__(self, request_id: str) -> None:
        super().__init__(f"Request '{request_id}' not found")
        self.request_id = request_id


class InvalidStatusTransitionError(Exception):
    """A programming error: the lifecycle only moves forward."""

    def __init__(self, request_id: str, current: str, new: str) -> None:
        super().__init__(f"Request '{request_id}' cannot go from '{current}' to '{new}'")


class ProcessingError(Exception):
    """Base class for expected failures of the pipeline. The request ends as 'failed'.

    `reason` is a short machine-readable code, used in logs (e.g. 'ai_refused').
    """

    reason = "processing_error"

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail or self.reason)
        self.detail = detail


class AiRefusalError(ProcessingError):
    """The AI answered with text that refuses or cannot do the task."""

    reason = "ai_refused"


class UnparseableAiResponseError(ProcessingError):
    """The AI answer has no usable JSON object, even after repairing it."""

    reason = "ai_unparseable"


class AiUnavailableError(ProcessingError):
    """The AI engine failed (network, timeout, 5xx) after all retries."""

    reason = "ai_unavailable"


class GuardrailViolationError(ProcessingError):
    """The extracted data is not safe or not valid to send."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason


class NotificationDeliveryError(ProcessingError):
    """The notification provider rejected the notification or kept failing."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
