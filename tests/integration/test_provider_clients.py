"""Adapters against a fake provider (httpx.MockTransport): real HTTP code, no network."""

import json

import httpx
import pytest

from app.domain.exceptions import (
    AiRefusalError,
    AiUnavailableError,
    NotificationDeliveryError,
    UnparseableAiResponseError,
)
from app.domain.models import Channel, Notification
from app.infrastructure.ai.ai_intent_extractor import AiIntentExtractor
from app.infrastructure.notifications.http_notification_sender import HttpNotificationSender
from app.infrastructure.notifications.rate_limiter import SlidingWindowRateLimiter


async def no_sleep(_: float) -> None:
    return None


def chat(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


def client_with(responses: list[httpx.Response], seen: list[httpx.Request]) -> httpx.AsyncClient:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return queue.pop(0)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://provider")


def extractor(client) -> AiIntentExtractor:
    return AiIntentExtractor(client, sleep=no_sleep)


def sender(client) -> HttpNotificationSender:
    return HttpNotificationSender(client, SlidingWindowRateLimiter(100, 10), sleep=no_sleep)


NOTIFICATION = Notification(to="feda@test.com", message="hola", channel=Channel.EMAIL)


async def test_extractor_sends_prompt_and_parses_answer():
    seen = []
    async with client_with([chat('{"to": "feda@test.com", "message": "hola", "type": "email"}')], seen) as client:
        intent = await extractor(client).extract("Manda un mail a feda@test.com diciendo hola")

    body = json.loads(seen[0].content)
    assert intent.to == "feda@test.com"
    assert seen[0].url.path == "/v1/ai/extract"
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][-1]["content"] == "Manda un mail a feda@test.com diciendo hola"


async def test_extractor_retries_transient_errors():
    seen = []
    responses = [httpx.Response(503), httpx.Response(429), chat('{"to": "a@b.com", "message": "x", "type": "email"}')]
    async with client_with(responses, seen) as client:
        intent = await extractor(client).extract("a@b.com")

    assert intent.to == "a@b.com"
    assert len(seen) == 3


async def test_extractor_gives_up_after_the_retries():
    seen = []
    async with client_with([httpx.Response(500)] * 3, seen) as client:
        with pytest.raises(AiUnavailableError):
            await extractor(client).extract("a@b.com")


async def test_extractor_does_not_retry_a_client_error():
    seen = []
    async with client_with([httpx.Response(401)], seen) as client:
        with pytest.raises(AiUnavailableError):
            await extractor(client).extract("a@b.com")

    assert len(seen) == 1


async def test_extractor_asks_again_once_when_the_answer_is_unreadable():
    seen = []
    responses = [chat("Here you go!"), chat('{"to": "a@b.com", "message": "x", "type": "email"}')]
    async with client_with(responses, seen) as client:
        intent = await extractor(client).extract("a@b.com")

    assert intent.to == "a@b.com"
    assert len(seen) == 2


async def test_extractor_unreadable_twice_fails():
    seen = []
    async with client_with([chat("???"), chat("???")], seen) as client:
        with pytest.raises(UnparseableAiResponseError):
            await extractor(client).extract("a@b.com")


async def test_extractor_does_not_retry_a_refusal():
    seen = []
    async with client_with([chat("Lo siento, no puedo hacerlo.")], seen) as client:
        with pytest.raises(AiRefusalError):
            await extractor(client).extract("a@b.com")

    assert len(seen) == 1


async def test_extractor_unexpected_body_shape_is_unparseable():
    seen = []
    async with client_with([httpx.Response(200, json={"foo": "bar"})] * 2, seen) as client:
        with pytest.raises(UnparseableAiResponseError):
            await extractor(client).extract("a@b.com")


async def test_sender_posts_the_provider_contract():
    seen = []
    async with client_with([httpx.Response(200, json={"status": "delivered"})], seen) as client:
        await sender(client).send(NOTIFICATION)

    assert seen[0].url.path == "/v1/notify"
    assert json.loads(seen[0].content) == {"to": "feda@test.com", "message": "hola", "type": "email"}


async def test_sender_retries_429_and_500():
    seen = []
    responses = [httpx.Response(429), httpx.Response(500), httpx.Response(200, json={"status": "delivered"})]
    async with client_with(responses, seen) as client:
        await sender(client).send(NOTIFICATION)

    assert len(seen) == 3


async def test_sender_rejected_payload_fails_without_retry():
    seen = []
    async with client_with([httpx.Response(422)], seen) as client:
        with pytest.raises(NotificationDeliveryError) as error:
            await sender(client).send(NOTIFICATION)

    assert error.value.reason == "notify_rejected"
    assert len(seen) == 1


async def test_sender_gives_up_when_the_provider_keeps_failing():
    seen = []
    async with client_with([httpx.Response(429)] * 4, seen) as client:
        with pytest.raises(NotificationDeliveryError) as error:
            await sender(client).send(NOTIFICATION)

    assert error.value.reason == "notify_unavailable"
    assert len(seen) == 4


async def test_sender_network_error_is_a_delivery_error():
    def handler(request):
        raise httpx.ConnectTimeout("timeout")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://provider") as client:
        with pytest.raises(NotificationDeliveryError):
            await sender(client).send(NOTIFICATION)
