"""Turns the raw text of the AI into an ExtractedIntent.

LLMs do not always follow the format. This parser tolerates what the mock (and real
models) return: markdown fences, text around the JSON, single quotes, unquoted keys,
truncated JSON, other key names and extra keys. It only fixes the FORMAT; whether the
data is valid is decided later by the domain guardrails.
"""

import ast
import json
import re

from app.domain.exceptions import AiRefusalError, UnparseableAiResponseError
from app.domain.models import ExtractedIntent

# First alias found wins. Keys are compared in lower case.
FIELD_ALIASES = {
    "to": ("to", "recipient", "destination", "destinatario", "address", "email", "phone"),
    "message": ("message", "body", "text", "content", "msg", "mensaje"),
    "type": ("type", "channel", "method", "tipo", "medium"),
}

_REFUSAL_MARKERS = (
    "lo siento", "no puedo", "no tengo permitido", "viola", "refused", "i cannot", "i can't", "unable to",
)
_CODE_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_UNQUOTED_KEY = re.compile(r"([{,]\s*)([A-Za-z_][\w-]*)(\s*:)")
_TRAILING_NOISE = re.compile(r"[\s.,…]+$")


MAX_RESPONSE_LENGTH = 10_000


def parse_ai_response(text: str) -> ExtractedIntent:
    if len(text) > MAX_RESPONSE_LENGTH:
        # A notification never needs this much text; also protects the parser from huge inputs.
        raise UnparseableAiResponseError("response too long")
    data = _load_json_object(text)
    if data is None:
        if _looks_like_refusal(text):
            raise AiRefusalError(text[:200])
        raise UnparseableAiResponseError(text[:200])
    return _to_intent(data)


def _load_json_object(text: str) -> dict | None:
    candidate = _json_candidate(text)
    if candidate is None:
        return None
    for attempt in _repair_attempts(candidate):
        data = _try_load(attempt)
        if isinstance(data, dict):
            return data
    return None


def _json_candidate(text: str) -> str | None:
    """The piece of text that should be the JSON object: inside a code fence, or from the first '{'."""
    fence = _CODE_FENCE.search(text)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    if start == -1:
        return None
    end = text.rfind("}")
    # No closing brace after the start: the JSON was truncated, keep everything.
    return text[start : end + 1] if end > start else text[start:]


def _repair_attempts(candidate: str):
    """From least to most invasive. Only reached when the previous attempt failed."""
    yield candidate
    repaired = _UNQUOTED_KEY.sub(r'\1"\2"\3', _TRAILING_NOISE.sub("", candidate))
    yield repaired
    # Truncated JSON: close the object (and an open string, if any).
    yield repaired + "}"
    yield repaired + '"}'


def _try_load(text: str):
    try:
        return json.loads(text)
    except ValueError:
        pass
    try:
        # Safe: literal_eval only builds literals, it never runs code. Accepts single quotes.
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None


def _to_intent(data: dict) -> ExtractedIntent:
    lowered = {str(key).strip().lower(): value for key, value in data.items()}
    return ExtractedIntent(**{field: _first_value(lowered, aliases) for field, aliases in FIELD_ALIASES.items()})


def _first_value(data: dict, aliases: tuple[str, ...]) -> str | None:
    for alias in aliases:
        value = data.get(alias)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _looks_like_refusal(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _REFUSAL_MARKERS) or lowered.startswith("error")
