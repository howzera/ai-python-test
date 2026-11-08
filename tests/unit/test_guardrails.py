import pytest

from app.domain.exceptions import GuardrailViolationError
from app.domain.guardrails import destinations_in, validate_intent
from app.domain.models import Channel, ExtractedIntent

EMAIL_INPUT = "Manda un mail a feda@test.com diciendo hola"
SMS_INPUT = "Avisar por SMS al 600-111-222 que la reserva ha sido confirmada."


def intent(to="feda@test.com", message="hola", type="email") -> ExtractedIntent:
    return ExtractedIntent(to=to, message=message, type=type)


def reason_of(intent_: ExtractedIntent, user_input: str) -> str:
    with pytest.raises(GuardrailViolationError) as error:
        validate_intent(intent_, user_input)
    return error.value.reason


def test_valid_email_notification():
    notification = validate_intent(intent(), EMAIL_INPUT)

    assert (notification.to, notification.message, notification.channel) == ("feda@test.com", "hola", Channel.EMAIL)


def test_phone_is_normalized_to_digits():
    notification = validate_intent(intent(to="600-111-222", message="confirmada", type="sms"), SMS_INPUT)

    assert notification.to == "600111222"
    assert notification.channel is Channel.SMS


def test_email_is_compared_case_insensitive():
    notification = validate_intent(intent(to="FEDA@Test.com"), EMAIL_INPUT)

    assert notification.to == "feda@test.com"


@pytest.mark.parametrize("raw_type, expected", [("EMAIL", Channel.EMAIL), ("correo", Channel.EMAIL), (" sms ", Channel.SMS)])
def test_type_synonyms_and_case(raw_type, expected):
    to = "feda@test.com" if expected is Channel.EMAIL else "600-111-222"
    user_input = EMAIL_INPUT if expected is Channel.EMAIL else SMS_INPUT

    assert validate_intent(intent(to=to, type=raw_type), user_input).channel is expected


def test_missing_type_is_inferred_from_the_destination():
    assert validate_intent(intent(type=None), EMAIL_INPUT).channel is Channel.EMAIL
    assert validate_intent(intent(to="600111222", type=None), SMS_INPUT).channel is Channel.SMS


def test_missing_destination_is_copied_from_the_input_when_unambiguous():
    notification = validate_intent(intent(to=None), EMAIL_INPUT)

    assert notification.to == "feda@test.com"


def test_missing_destination_with_two_candidates_fails():
    assert reason_of(intent(to=None), "Manda un mail a a@test.com o a b@test.com") == "missing_destination"


def test_missing_destination_without_candidates_fails():
    assert reason_of(intent(to=None), "Avisa a Pedro de que llego tarde") == "missing_destination"


def test_destination_not_written_by_the_user_is_rejected():
    # Hallucination or prompt injection: the AI returned a recipient the user never wrote.
    assert reason_of(intent(to="attacker@evil.com"), EMAIL_INPUT) == "destination_not_in_input"


def test_unknown_type_is_rejected():
    assert reason_of(intent(type="whatsapp"), EMAIL_INPUT) == "invalid_type"


def test_type_inconsistent_with_destination_is_rejected():
    assert reason_of(intent(type="sms"), EMAIL_INPUT) == "invalid_phone"
    assert reason_of(intent(to="600-111-222", type="email"), SMS_INPUT) == "invalid_email"


@pytest.mark.parametrize("message", [None, "", "   "])
def test_empty_message_is_rejected(message):
    assert reason_of(intent(message=message), EMAIL_INPUT) == "missing_message"


def test_too_long_message_is_rejected():
    assert reason_of(intent(message="x" * 1001), EMAIL_INPUT) == "message_too_long"


def test_destinations_in_text():
    text = "Correo a Ana@x.com y SMS al +34 600 111 222; cita a las 10:00 del 2026"

    assert destinations_in(text) == {"ana@x.com", "+34600111222"}
