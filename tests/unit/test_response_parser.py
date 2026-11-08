"""One test per response variation of the mock (provider/responses.py)."""

import pytest

from app.domain.exceptions import AiRefusalError, UnparseableAiResponseError
from app.domain.models import ExtractedIntent
from app.infrastructure.ai.prompts import build_messages
from app.infrastructure.ai.response_parser import parse_ai_response

T, M, K = "feda@test.com", "hola", "email"
FULL = ExtractedIntent(to=T, message=M, type=K)

PARSEABLE_VARIATIONS = {
    # 50%: perfect JSON
    "perfect": (f'{{"to": "{T}", "message": "{M}", "type": "{K}"}}', FULL),
    # 10%: other key names
    "keys_recipient_body_channel": (f'{{"Recipient": "{T}", "body": "{M}", "channel": "{K}"}}', FULL),
    "keys_capitalized": (f'{{"To": "{T}", "Message": "{M}", "Type": "{K}"}}', FULL),
    "keys_destination_text_method": (f'{{"destination": "{T}", "text": "{M}", "method": "{K}"}}', FULL),
    # 10%: extra or missing fields
    "extra_fields": (f'{{"to": "{T}", "message": "{M}", "type": "{K}", "confidence": 0.99, "latency_ms": 120}}', FULL),
    "missing_type": (f'{{"to": "{T}", "message": "{M}"}}', ExtractedIntent(to=T, message=M, type=None)),
    "missing_destination": (f'{{"message": "{M}", "type": "{K}"}}', ExtractedIntent(to=None, message=M, type=K)),
    # 10%: JSON wrapped in text
    "json_code_block": (f'He extraído la información correctamente:\n```json\n{{"to": "{T}", "message": "{M}", "type": "{K}"}}\n```', FULL),
    "generic_code_block": (f'Output:\n```\n{{"to": "{T}", "message": "{M}", "type": "{K}"}}\n```', FULL),
    "embedded_in_text": (f'Claro, el destino es {T} y enviaré {M} por {K}. En formato JSON: {{"to": "{T}", "message": "{M}", "type": "{K}"}}', FULL),
    # 10%: malformed JSON
    "truncated": (f'{{"to": "{T}", "message": "{M}", "type": "{K}" ...', FULL),
    "single_quotes": (f"{{'to': '{T}', 'message': '{M}', 'type': '{K}'}}", FULL),
    "unquoted_keys": (f'{{to: "{T}", message: "{M}", type: "{K}"}}', FULL),
}

REFUSALS = {
    "privacy_refusal": "Lo siento, como IA no tengo permitido procesar datos de contacto personales.",
    "policy_error": "Error: El contenido del mensaje viola las políticas de seguridad (Potential Spam).",
    "refused": "Refused: Content analysis flagged sensitive information.",
    "missing_entities": "I cannot process the request. I was unable to identify the destination (email/phone) in your prompt.",
}


@pytest.mark.parametrize("raw, expected", PARSEABLE_VARIATIONS.values(), ids=PARSEABLE_VARIATIONS.keys())
def test_parses_every_mock_variation(raw, expected):
    assert parse_ai_response(raw) == expected


@pytest.mark.parametrize("raw", REFUSALS.values(), ids=REFUSALS.keys())
def test_refusals_are_detected(raw):
    with pytest.raises(AiRefusalError):
        parse_ai_response(raw)


@pytest.mark.parametrize("raw", ["", "Here you go!", '{"to": "a@b.com", "mess', "[1, 2, 3]"])
def test_text_without_a_usable_object_is_unparseable(raw):
    with pytest.raises(UnparseableAiResponseError):
        parse_ai_response(raw)


def test_null_values_are_treated_as_missing():
    assert parse_ai_response('{"to": null, "message": "hola", "type": null}') == ExtractedIntent(None, "hola", None)


def test_numeric_phone_is_converted_to_string():
    assert parse_ai_response('{"to": 600111222, "message": "hola", "type": "sms"}').to == "600111222"


def test_user_input_goes_last_and_unchanged():
    messages = build_messages("Manda un mail a feda@test.com diciendo hola")

    assert messages[0]["role"] == "system"
    assert messages[-1] == {"role": "user", "content": "Manda un mail a feda@test.com diciendo hola"}
