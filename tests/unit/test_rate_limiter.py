from app.infrastructure.notifications.rate_limiter import SlidingWindowRateLimiter
from tests.fakes import FakeClock


async def test_calls_under_the_limit_do_not_wait():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(max_calls=3, period=10, clock=clock, sleep=clock.sleep)

    for _ in range(3):
        await limiter.acquire()

    assert clock.sleeps == []


async def test_extra_call_waits_until_the_oldest_leaves_the_window():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(max_calls=2, period=10, clock=clock, sleep=clock.sleep)

    await limiter.acquire()  # t=0
    clock.now = 4
    await limiter.acquire()  # t=4
    await limiter.acquire()  # must wait until t=10

    assert clock.sleeps == [6]
    assert clock.now == 10


async def test_window_slides():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(max_calls=1, period=10, clock=clock, sleep=clock.sleep)

    await limiter.acquire()
    clock.now = 10.5
    await limiter.acquire()

    assert clock.sleeps == []
