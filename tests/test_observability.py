import asyncio
import io
import json
import logging
from types import SimpleNamespace

import httpx
import pytest

from ai_tutor import llm, observability


@pytest.fixture
def logged(monkeypatch):
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(logging.Formatter("%(message)s"))
    monkeypatch.setattr(observability.logger, "handlers", [handler])
    monkeypatch.setattr(observability.logger, "level", logging.INFO)
    return lambda: [json.loads(line) for line in output.getvalue().splitlines()]


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
def test_stream_logs_final_outcome_without_buffering_or_private_content(logged, outcome):
    delivered = []
    secret = "secret-key-and-student-text"

    async def app(scope, receive, send):
        observability.mark_chat_started()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        observability.mark_first_text()
        await send({"type": "http.response.body", "body": secret.encode(), "more_body": True})
        assert delivered[-1]["body"] == secret.encode()
        assert logged() == []
        if outcome == "cancelled":
            raise asyncio.CancelledError()
        if outcome == "failed":
            observability.mark_outcome("failed", RuntimeError(secret))
        else:
            observability.mark_outcome("completed")
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def send(message):
        delivered.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": f"/private/{secret}",
        "query_string": secret.encode(),
        "headers": [(b"authorization", secret.encode())],
        "route": SimpleNamespace(path="/api/chat"),
    }
    if outcome == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(observability.RequestLoggingMiddleware(app)(scope, None, send))
    else:
        asyncio.run(observability.RequestLoggingMiddleware(app)(scope, None, send))
    event = logged()[0]
    assert event["outcome"] == outcome
    assert event["status"] == 200
    assert event["first_text_ms"] is not None
    assert event["response_complete"] == (outcome != "cancelled")
    assert event["route"] == "/api/chat"
    assert event["request_id"].encode() in dict(delivered[0]["headers"]).values()
    assert secret not in json.dumps(logged())
    assert observability.current_request.get() is None


@pytest.mark.parametrize("status,outcome", [(401, "rejected"), (429, "busy"), (503, "failed")])
def test_request_rejection_classification(logged, status, outcome):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": status})
        await send({"type": "http.response.body", "body": b""})

    async def send(message):
        pass

    asyncio.run(
        observability.RequestLoggingMiddleware(app)({"type": "http", "method": "GET"}, None, send)
    )
    assert logged()[0]["outcome"] == outcome


def test_provider_timeout_shares_request_id_and_excludes_exception_secrets(logged):
    observation = observability.RequestObservation()
    token = observability.current_request.set(observation)
    try:
        with (
            pytest.raises(httpx.ReadTimeout),
            observability.observe_provider("azure", "tts", "voice"),
        ):
            raise httpx.ReadTimeout("credential-and-ssml-secret")
    finally:
        observability.current_request.reset(token)
    event = logged()[0]
    assert event["request_id"] == observation.request_id
    assert event["outcome"] == "failed"
    assert event["reason"] == "timeout"
    assert "credential-and-ssml-secret" not in json.dumps(event)


def test_stream_usage_is_recorded_without_logging_provider_content(monkeypatch, logged):
    body = (
        'data: {"choices":[{"delta":{"content":"private-answer"}}]}\n\n'
        'data: {"choices":[],"usage":{"prompt_tokens":100,"completion_tokens":20,'
        '"cost":0.001,"private_field":"private-secret"}}\n\n'
        "data: [DONE]\n\n"
    )
    client = httpx.Client(
        base_url="https://example.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body)),
    )
    monkeypatch.setattr(llm, "build_client", lambda: client)
    assert list(llm.ChatClient().stream([])) == ["private-answer"]
    event = logged()[0]
    assert event["outcome"] == "completed"
    assert event["prompt_tokens"] == 100
    assert event["completion_tokens"] == 20
    assert event["cost"] == 0.001
    assert "private" not in json.dumps(event)


def test_closing_provider_stream_records_cancellation_and_closes_client(monkeypatch, logged):
    body = 'data: {"choices":[{"delta":{"content":"partial"}}]}\n\ndata: [DONE]\n\n'
    client = httpx.Client(
        base_url="https://example.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body)),
    )
    monkeypatch.setattr(llm, "build_client", lambda: client)
    stream = llm.ChatClient().stream([])
    assert next(stream) == "partial"
    stream.close()
    assert client.is_closed
    assert logged()[0]["outcome"] == "cancelled"


def test_groq_throttling_is_logged_without_recording_audio(monkeypatch, logged):
    from ai_tutor import stt
    from ai_tutor.config import get_settings

    monkeypatch.setattr(get_settings(), "groq_api_key", "private-groq-key")
    client = httpx.Client(
        base_url="https://example.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(429, text="private-body")),
    )
    monkeypatch.setattr(stt.httpx, "Client", lambda **kwargs: client)
    with pytest.raises(stt.SttError):
        stt.transcribe(b"private-audio" * 50, "clip.webm", "audio/webm")
    event = logged()[0]
    assert event["provider"] == "groq"
    assert event["status"] == 429 and event["outcome"] == "failed"
    assert "private" not in json.dumps(event)


def test_azure_error_is_logged_without_recording_ssml(monkeypatch, logged):
    from ai_tutor import tts

    response = httpx.Response(
        503, text="private-body", request=httpx.Request("POST", "https://example.test")
    )
    monkeypatch.setattr(tts.httpx, "post", lambda *args, **kwargs: response)
    with pytest.raises(tts.TtsError):
        tts._synth_chunk.__wrapped__("private-ssml", "ar-SA-HamedNeural", "0%")
    event = logged()[0]
    assert event["provider"] == "azure"
    assert event["status"] == 503 and event["outcome"] == "failed"
    assert "private" not in json.dumps(event)
