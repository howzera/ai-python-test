"""Business guardrails: decide if what the AI extracted is safe and valid to send.

Pure functions, no I/O: easy to test and to explain. The AI is treated as an
untrusted source; the original user text is the source of truth.
"""

import re

from app.domain.exceptions import GuardrailViolationError
from app.domain.models import Channel, ExtractedIntent, Notification

MAX_MESSAGE_LENGTH = 1000

_EMAIL = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")
_PHONE = re.compile(r"^\+?\d{9,15}$")
# Candidates inside free text: emails, and digit groups with optional separators.
_EMAIL_IN_TEXT = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE_IN_TEXT = re.compile(r"\+?\d[\d\s.\-()]{7,}\d")

_CHANNEL_ALIASES = {
    "email": Channel.EMAIL,
    "e-mail": Channel.EMAIL,
    "mail": Channel.EMAIL,
    "correo": Channel.EMAIL,
    "sms": Channel.SMS,
    "text": Channel.SMS,
    "phone": Channel.SMS,
    "telefono": Channel.SMS,
    "teléfono": Channel.SMS,
}


def validate_intent(intent: ExtractedIntent, user_input: str) -> Notification:
    """Return a safe Notification or raise GuardrailViolationError with a reason code."""
    candidates = destinations_in(user_input)

    to = normalize_destination(intent.to) if intent.to else None
    if to is None:
        # The AI omitted the recipient. Take it from the user text only if it is unambiguous:
        # we copy what the user wrote, we never guess.
        if len(candidates) != 1:
            raise GuardrailViolationError("missing_destination")
        to = next(iter(candidates))

    # Anti-hallucination and anti-injection: the recipient must be written in the user text.
    if to not in candidates:
        raise GuardrailViolationError("destination_not_in_input", f"'{to}' is not in the user input")

    channel = parse_channel(intent.type) if intent.type else infer_channel(to)
    if channel is None:
        raise GuardrailViolationError("invalid_type", f"unknown type '{intent.type}'")
    if channel is Channel.EMAIL and not _EMAIL.match(to):
        raise GuardrailViolationError("invalid_email", f"'{to}' is not an email address")
    if channel is Channel.SMS and not _PHONE.match(to):
        raise GuardrailViolationError("invalid_phone", f"'{to}' is not a phone number")

    message = (intent.message or "").strip()
    if not message:
        raise GuardrailViolationError("missing_message")
    if len(message) > MAX_MESSAGE_LENGTH:
        raise GuardrailViolationError("message_too_long")

    return Notification(to=to, message=message, channel=channel)


def normalize_destination(value: str) -> str:
    """Emails in lower case; phones as digits only (with an optional leading '+')."""
    value = value.strip()
    if "@" in value:
        return value.lower()
    prefix = "+" if value.startswith("+") else ""
    return prefix + re.sub(r"\D", "", value)


def destinations_in(text: str) -> set[str]:
    """All emails and phone numbers written in the text, normalized."""
    found = {normalize_destination(m) for m in _EMAIL_IN_TEXT.findall(text)}
    for match in _PHONE_IN_TEXT.findall(text):
        phone = normalize_destination(match)
        if _PHONE.match(phone):
            found.add(phone)
    return found


def parse_channel(value: str) -> Channel | None:
    return _CHANNEL_ALIASES.get(value.strip().lower())


def infer_channel(to: str) -> Channel | None:
    if _EMAIL.match(to):
        return Channel.EMAIL
    if _PHONE.match(to):
        return Channel.SMS
    return None
