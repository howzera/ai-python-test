import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx

from app.domain.exceptions import AiUnavailableError, UnparseableAiResponseError
from app.domain.models import ExtractedIntent
from app.infrastructure.ai.prompts import build_messages
from app.infrastructure.ai.response_parser import parse_ai_response
from app.infrastructure.http_retry import retry_policy

logger = logging.getLogger(__name__)


class AiIntentExtractor:
    """IntentExtractor adapter for the AI engine (/v1/ai/extract).

    Transport errors (network, timeout, 429, 5xx) are retried with backoff. An unreadable
    answer gets one extra call; a refusal is not retried.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        max_concurrency: int = 100,
        format_retries: int = 1,
        retry_attempts: int = 3,
        retry_initial_wait: float = 0.5,
        retry_max_wait: float = 4.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        # Bulkhead: limits parallel calls to the (slow, expensive) AI engine.
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._format_retries = format_retries
        self._retry = lambda: retry_policy(retry_attempts, retry_initial_wait, retry_max_wait, sleep)

    async def extract(self, user_input: str) -> ExtractedIntent:
        for attempt in range(1, self._format_retries + 2):
            content = await self._complete(user_input)
            try:
                return parse_ai_response(content)
            except UnparseableAiResponseError:
                logger.warning("unreadable AI answer (attempt %d): %r", attempt, content[:120])
        raise UnparseableAiResponseError("unreadable AI answer after retries")

    async def _complete(self, user_input: str) -> str:
        payload = {"messages": build_messages(user_input), "temperature": 0}
        try:
            async with self._semaphore:
                async for attempt in self._retry():
                    with attempt:
                        response = await self._client.post("/v1/ai/extract", json=payload)
                        response.raise_for_status()
        except httpx.HTTPError as error:
            raise AiUnavailableError(str(error) or type(error).__name__) from error

        try:
            return response.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise UnparseableAiResponseError("unexpected AI response shape") from error
