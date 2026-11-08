"""The whole service (router -> use cases -> adapters) against a fake provider."""

import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def fake_provider(ai_content: str, notify_status: int = 200):
    calls = {"extract": 0, "notify": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "test-dev-2026"
        if request.url.path == "/v1/ai/extract":
            calls["extract"] += 1
            return httpx.Response(200, json={"choices": [{"message": {"content": ai_content}}]})
        calls["notify"] += 1
        return httpx.Response(notify_status, json={"status": "delivered", "provider_id": "p-1"})

    return httpx.MockTransport(handler), calls


def client_for(ai_content: str, notify_status: int = 200):
    transport, calls = fake_provider(ai_content, notify_status)
    return TestClient(create_app(Settings(), transport=transport)), calls


def wait_for_final_status(client: TestClient, request_id: str) -> str:
    for _ in range(100):
        status = client.get(f"/v1/requests/{request_id}").json()["status"]
        if status in ("sent", "failed"):
            return status
        time.sleep(0.01)
    raise AssertionError("request did not finish")


GOOD = '```json\n{"To": "feda@test.com", "Message": "hola", "Type": "email"}\n```'
INPUT = {"user_input": "Manda un mail a feda@test.com diciendo hola"}


def test_full_flow_create_process_and_sent():
    client, calls = client_for(GOOD)
    with client:
        created = client.post("/v1/requests", json=INPUT)
        request_id = created.json()["id"]
        queued = client.get(f"/v1/requests/{request_id}")
        processed = client.post(f"/v1/requests/{request_id}/process")
        final = wait_for_final_status(client, request_id)
        again = client.post(f"/v1/requests/{request_id}/process")

    assert created.status_code == 201
    assert queued.json() == {"id": request_id, "status": "queued"}
    assert processed.status_code == 202
    assert final == "sent"
    assert again.status_code == 200 and again.json()["status"] == "sent"
    assert calls == {"extract": 1, "notify": 1}


def test_refusal_ends_failed_and_nothing_is_sent():
    client, calls = client_for("Lo siento, como IA no tengo permitido procesar datos de contacto personales.")
    with client:
        request_id = client.post("/v1/requests", json=INPUT).json()["id"]
        client.post(f"/v1/requests/{request_id}/process")
        final = wait_for_final_status(client, request_id)

    assert final == "failed"
    assert calls["notify"] == 0


def test_rejected_notification_ends_failed():
    client, _ = client_for(GOOD, notify_status=422)
    with client:
        request_id = client.post("/v1/requests", json=INPUT).json()["id"]
        client.post(f"/v1/requests/{request_id}/process")

        assert wait_for_final_status(client, request_id) == "failed"


@pytest.mark.parametrize("path, method", [("/v1/requests/nope", "get"), ("/v1/requests/nope/process", "post")])
def test_unknown_id_is_404(path, method):
    client, _ = client_for(GOOD)
    with client:
        response = getattr(client, method)(path)

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.parametrize("body", [{}, {"user_input": ""}, {"user_input": "   "}, {"user_input": "x" * 2001}, {"user_input": 5}])
def test_invalid_input_is_422(body):
    client, _ = client_for(GOOD)
    with client:
        assert client.post("/v1/requests", json=body).status_code == 422
