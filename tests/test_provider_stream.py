import httpx
import pytest

from ai_tutor import llm


@pytest.mark.parametrize(
    "body",
    [
        'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',
        'data: {"error":{"message":"failed"}}\n\ndata: [DONE]\n\n',
        'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\ndata: [DONE]\n\n',
    ],
)
def test_unfinished_provider_stream_raises(monkeypatch, body):
    client = httpx.Client(
        base_url="https://example.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body)),
    )
    monkeypatch.setattr(llm, "build_client", lambda: client)
    with pytest.raises(RuntimeError):
        list(llm.ChatClient().stream([]))
    assert client.is_closed


def test_finished_provider_stream_accepts_usage_events(monkeypatch):
    body = 'data: {"choices":[{"delta":{"content":"مرحبا"}}]}\n\ndata: {"choices":[],"usage":{}}\n\ndata: [DONE]\n\n'
    client = httpx.Client(
        base_url="https://example.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body)),
    )
    monkeypatch.setattr(llm, "build_client", lambda: client)
    assert list(llm.ChatClient().stream([])) == ["مرحبا"]
    assert client.is_closed


def test_request_deadline_bounds_provider_timeout(monkeypatch):
    import time

    from ai_tutor.openrouter import constrain_request, generation_deadline

    request = httpx.Request("POST", "https://example.test")
    token = generation_deadline.set(time.monotonic() + 2)
    try:
        constrain_request(request)
        assert 0 < request.extensions["timeout"]["read"] <= 2
    finally:
        generation_deadline.reset(token)
    token = generation_deadline.set(time.monotonic() - 1)
    try:
        with pytest.raises(TimeoutError):
            constrain_request(request)
    finally:
        generation_deadline.reset(token)


def test_embedding_client_can_be_reused_until_context_exit(monkeypatch):
    from ai_tutor import embeddings

    client = httpx.Client(
        base_url="https://example.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"data": [{"embedding": [1.0, 2.0]}]})
        ),
    )
    monkeypatch.setattr(embeddings, "build_client", lambda: client)
    with embeddings.EmbeddingClient() as embedder:
        assert embedder.embed_one("first") == [1.0, 2.0]
        assert embedder.embed_one("second") == [1.0, 2.0]
        assert not client.is_closed
    assert client.is_closed
