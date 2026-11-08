import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.application.create_request import CreateNotificationRequest
from app.application.get_request import GetNotificationRequest
from app.application.process_request import ProcessNotificationRequest
from app.config import Settings
from app.infrastructure.ai.ai_intent_extractor import AiIntentExtractor
from app.infrastructure.background.asyncio_job_scheduler import AsyncioJobScheduler
from app.infrastructure.http_api.request_router import register_exception_handlers, router
from app.infrastructure.notifications.http_notification_sender import HttpNotificationSender
from app.infrastructure.notifications.rate_limiter import SlidingWindowRateLimiter
from app.infrastructure.persistence.in_memory_request_repository import InMemoryRequestRepository

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
# httpx logs every request at INFO: too noisy under load.
logging.getLogger("httpx").setLevel(logging.WARNING)


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    """Composition root: the only place that knows every concrete adapter.

    `transport` lets the tests replace the real provider with a fake one.
    """
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        headers = {"X-API-Key": settings.provider_api_key}
        limits = httpx.Limits(max_connections=200, max_keepalive_connections=200)
        # One client (one connection pool) per dependency, each with its own timeout.
        async with (
            httpx.AsyncClient(
                base_url=settings.provider_base_url, headers=headers, limits=limits,
                timeout=settings.ai_timeout_seconds, transport=transport,
            ) as ai_client,
            httpx.AsyncClient(
                base_url=settings.provider_base_url, headers=headers, limits=limits,
                timeout=settings.notify_timeout_seconds, transport=transport,
            ) as notify_client,
        ):
            repository = InMemoryRequestRepository()
            scheduler = AsyncioJobScheduler()
            extractor = AiIntentExtractor(ai_client, max_concurrency=settings.ai_max_concurrency)
            sender = HttpNotificationSender(
                notify_client,
                SlidingWindowRateLimiter(settings.notify_rate_limit_calls, settings.notify_rate_limit_period_seconds),
            )
            app.state.create_request = CreateNotificationRequest(repository)
            app.state.get_request = GetNotificationRequest(repository)
            app.state.process_request = ProcessNotificationRequest(repository, extractor, sender, scheduler)
            yield
            await scheduler.shutdown()

    app = FastAPI(title="Intelligent Notification Service", version="1.0.0", lifespan=lifespan)
    app.include_router(router)
    register_exception_handlers(app)
    return app


app = create_app()
