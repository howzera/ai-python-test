import pytest

from app.application.create_request import CreateNotificationRequest
from app.application.get_request import GetNotificationRequest
from app.application.process_request import ProcessNotificationRequest
from app.domain.exceptions import AiRefusalError, RequestNotFoundError
from app.domain.models import Channel, ExtractedIntent, RequestStatus
from app.infrastructure.persistence.in_memory_request_repository import InMemoryRequestRepository
from tests.fakes import FakeExtractor, FakeSender, ManualScheduler, delivery_error

USER_INPUT = "Manda un mail a feda@test.com diciendo hola"
GOOD_INTENT = ExtractedIntent(to="feda@test.com", message="hola", type="email")


@pytest.fixture
def repository():
    return InMemoryRequestRepository()


@pytest.fixture
def scheduler():
    return ManualScheduler()


def build(repository, scheduler, extractor=None, sender=None):
    extractor = extractor or FakeExtractor(GOOD_INTENT)
    sender = sender or FakeSender()
    return ProcessNotificationRequest(repository, extractor, sender, scheduler), extractor, sender


async def create(repository) -> str:
    return (await CreateNotificationRequest(repository).execute(USER_INPUT)).id


async def status_of(repository, request_id) -> RequestStatus:
    return (await GetNotificationRequest(repository).execute(request_id)).status


async def test_new_request_is_queued(repository):
    request_id = await create(repository)

    assert await status_of(repository, request_id) is RequestStatus.QUEUED


async def test_process_accepts_and_runs_in_background(repository, scheduler):
    process, _, sender = build(repository, scheduler)
    request_id = await create(repository)

    result = await process.execute(request_id)

    assert result.status is RequestStatus.PROCESSING
    assert sender.sent == []  # nothing sent until the background job runs

    await scheduler.run_all()

    assert await status_of(repository, request_id) is RequestStatus.SENT
    assert sender.sent[0].channel is Channel.EMAIL


async def test_process_twice_runs_the_pipeline_once(repository, scheduler):
    process, extractor, _ = build(repository, scheduler)
    request_id = await create(repository)

    await process.execute(request_id)
    await process.execute(request_id)
    await scheduler.run_all()
    final = await process.execute(request_id)

    assert len(extractor.calls) == 1
    assert final.status is RequestStatus.SENT


async def test_unknown_request_raises_not_found(repository, scheduler):
    process, _, _ = build(repository, scheduler)

    with pytest.raises(RequestNotFoundError):
        await process.execute("does-not-exist")
    with pytest.raises(RequestNotFoundError):
        await GetNotificationRequest(repository).execute("does-not-exist")


async def test_ai_refusal_ends_failed_without_sending(repository, scheduler):
    process, _, sender = build(repository, scheduler, extractor=FakeExtractor(error=AiRefusalError("Lo siento")))
    request_id = await create(repository)

    await process.execute(request_id)
    await scheduler.run_all()

    request = await GetNotificationRequest(repository).execute(request_id)
    assert request.status is RequestStatus.FAILED
    assert request.failure_reason == "ai_refused"
    assert sender.sent == []


async def test_guardrail_violation_ends_failed(repository, scheduler):
    hallucinated = ExtractedIntent(to="someone@else.com", message="hola", type="email")
    process, _, sender = build(repository, scheduler, extractor=FakeExtractor(hallucinated))
    request_id = await create(repository)

    await process.execute(request_id)
    await scheduler.run_all()

    request = await GetNotificationRequest(repository).execute(request_id)
    assert request.failure_reason == "destination_not_in_input"
    assert sender.sent == []


async def test_delivery_failure_ends_failed(repository, scheduler):
    process, _, _ = build(repository, scheduler, sender=FakeSender(fail_with=delivery_error()))
    request_id = await create(repository)

    await process.execute(request_id)
    await scheduler.run_all()

    assert await status_of(repository, request_id) is RequestStatus.FAILED


async def test_unexpected_error_never_leaves_the_request_processing(repository, scheduler):
    process, _, _ = build(repository, scheduler, extractor=FakeExtractor(error=KeyError("bug")))
    request_id = await create(repository)

    await process.execute(request_id)
    await scheduler.run_all()

    request = await GetNotificationRequest(repository).execute(request_id)
    assert request.status is RequestStatus.FAILED
    assert request.failure_reason == "internal_error"
