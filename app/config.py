import os
from dataclasses import dataclass


def _float_env(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _int_env(name: str, default: int) -> int:
    return int(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    """Runtime configuration, read from environment variables (12-factor style)."""

    provider_base_url: str = "http://localhost:3001"
    # Test key from the statement. In production it comes from a secret manager, never from code.
    provider_api_key: str = "test-dev-2026"
    ai_timeout_seconds: float = 10.0
    ai_max_concurrency: int = 100
    notify_timeout_seconds: float = 5.0
    # The provider allows 50 per 10 s; we keep a small margin.
    notify_rate_limit_calls: int = 48
    notify_rate_limit_period_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            provider_base_url=os.getenv("PROVIDER_BASE_URL", cls.provider_base_url),
            provider_api_key=os.getenv("PROVIDER_API_KEY", cls.provider_api_key),
            ai_timeout_seconds=_float_env("AI_TIMEOUT_SECONDS", cls.ai_timeout_seconds),
            ai_max_concurrency=_int_env("AI_MAX_CONCURRENCY", cls.ai_max_concurrency),
            notify_timeout_seconds=_float_env("NOTIFY_TIMEOUT_SECONDS", cls.notify_timeout_seconds),
            notify_rate_limit_calls=_int_env("NOTIFY_RATE_LIMIT_CALLS", cls.notify_rate_limit_calls),
            notify_rate_limit_period_seconds=_float_env(
                "NOTIFY_RATE_LIMIT_PERIOD_SECONDS", cls.notify_rate_limit_period_seconds
            ),
        )
