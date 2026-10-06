import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from ai_tutor import db as database
from ai_tutor.api import main
from ai_tutor.config import get_settings
from ai_tutor.db import Base
from ai_tutor.embeddings import EmbeddingClient
from ai_tutor.llm import ChatClient
from ai_tutor.models import Book, ChatSession, Chunk, Message

STUDENT = "a" * 24
TENANT = "b" * 24


@pytest.fixture
def api(monkeypatch):
    url = os.environ.get("TUTOR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TUTOR_TEST_DATABASE_URL for PostgreSQL integration tests")
    schema = f"tutor_test_{uuid.uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema},public"})
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        Base.metadata.create_all(engine, checkfirst=False)
        monkeypatch.setattr(main, "engine", engine)
        monkeypatch.setattr(main, "SessionLocal", factory)
        monkeypatch.setattr(database, "SessionLocal", factory)
        monkeypatch.setattr(get_settings(), "tutor_service_token", "test-service-token")
        monkeypatch.setattr(get_settings(), "openrouter_api_key", "unused-test-key")
        vector = [1.0] + [0.0] * (get_settings().embedding_dim - 1)
        monkeypatch.setattr(EmbeddingClient, "embed_one", lambda self, value: vector)
        monkeypatch.setattr(EmbeddingClient, "embed", lambda self, values: [vector for _ in values])
        seen = []

        def stream(self, messages, temperature=0.4):
            seen.append(messages)
            yield "القوة "
            yield "تؤثر على الحركة."

        monkeypatch.setattr(ChatClient, "stream", stream)
        with factory.begin() as db:
            book = Book(title="علوم", grade="8", subject="العلوم", file_path="test.pdf")
            other = Book(title="علوم رابع", grade="4", subject="العلوم", file_path="test.pdf")
            db.add_all([book, other])
            db.flush()
            db.add(
                Chunk(
                    book_id=book.id,
                    page_start=15,
                    page_end=15,
                    section="القوة",
                    content="القوة تؤثر على الحركة.",
                    token_count=10,
                    embedding=vector,
                )
            )
            book_id, other_id = str(book.id), str(other.id)
        headers = {
            "Authorization": "Bearer test-service-token",
            "X-Tutor-Student": STUDENT,
            "X-Tutor-Tenant": TENANT,
            "X-Tutor-Grade": "Grade 8",
        }
        with TestClient(main.app) as client:
            yield client, headers, book_id, other_id, factory, seen
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def session(api):
    client, headers, book_id, *_ = api
    response = client.post("/api/sessions", headers=headers, json={"book_id": book_id})
    assert response.status_code == 201
    return response.json()["session_id"]


def events(response):
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


def test_auth_catalog_and_grade_enforcement(api, monkeypatch):
    client, headers, book_id, other_id, *_ = api
    for path in ("/api/books", "/api/sessions"):
        assert client.get(path).status_code == 401
    assert (
        client.post("/api/chat", json={"session_id": str(uuid.uuid4()), "message": "x"}).status_code
        == 401
    )
    assert client.get("/").status_code == 404
    assert client.get("/health").status_code == 200
    assert [book["id"] for book in client.get("/api/books", headers=headers).json()] == [book_id]
    assert (
        client.post("/api/sessions", headers=headers, json={"book_id": other_id}).status_code == 404
    )
    assert client.post("/api/sessions", headers=headers, json={}).status_code == 422
    assert (
        client.get("/api/books", headers={**headers, "X-Tutor-Tenant": "invalid"}).status_code
        == 400
    )
    monkeypatch.setattr(get_settings(), "tutor_service_token", "")
    assert client.get("/api/books", headers=headers).status_code == 503


def test_stream_persistence_followups_and_owner_isolation(api):
    client, headers, _, _, factory, seen = api
    sid = session(api)
    response = client.post(
        "/api/chat", headers=headers, json={"session_id": sid, "message": "شو هي القوة؟"}
    )
    assert response.status_code == 200
    data = events(response)
    assert data[0]["sources"] == [{"page": 15, "section": "القوة"}]
    assert data[-1] == {"done": True}
    assert "".join(item.get("delta", "") for item in data) == "القوة تؤثر على الحركة."
    history = client.get(f"/api/sessions/{sid}/messages", headers=headers).json()
    assert [m["role"] for m in history["messages"]] == ["user", "assistant"]
    assert history["messages"][-1]["sources"] == data[0]["sources"]
    assert history["session"]["session_id"] == sid
    assert (
        client.post(
            "/api/chat", headers=headers, json={"session_id": sid, "message": "طيب وضح أكثر"}
        ).status_code
        == 200
    )
    assert any(m["role"] == "assistant" for m in seen[-1])
    for changed in ({"X-Tutor-Student": "c" * 24}, {"X-Tutor-Tenant": "d" * 24}):
        outsider = {**headers, **changed}
        assert client.get("/api/sessions", headers=outsider).json() == []
        assert client.get(f"/api/sessions/{sid}/messages", headers=outsider).status_code == 404
        assert (
            client.post(
                "/api/chat", headers=outsider, json={"session_id": sid, "message": "x"}
            ).status_code
            == 404
        )
    assert (
        client.get(
            f"/api/sessions/{sid}/messages", headers={**headers, "X-Tutor-Grade": "4"}
        ).status_code
        == 403
    )
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 4


def test_failed_generation_rolls_back_partial_turn(api, monkeypatch):
    client, headers, _, _, factory, _ = api
    sid = session(api)

    def broken(self, messages, temperature=0.4):
        yield "نص جزئي"
        raise RuntimeError("provider-secret-that-must-not-leak")

    monkeypatch.setattr(ChatClient, "stream", broken)
    response = client.post(
        "/api/chat", headers=headers, json={"session_id": sid, "message": "صفحة 15"}
    )
    data = events(response)
    assert "error" in data[-1]
    assert not any(item.get("done") for item in data)
    assert "provider-secret" not in response.text
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 0
        assert not db.get(ChatSession, uuid.UUID(sid)).pinned_chunk_ids


def test_conversation_lock_and_input_limits(api):
    client, headers, _, _, factory, _ = api
    sid = session(api)
    key = int.from_bytes(uuid.UUID(sid).bytes[:8], "big", signed=True)
    with factory() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        assert (
            client.post(
                "/api/chat", headers=headers, json={"session_id": sid, "message": "x"}
            ).status_code
            == 409
        )
    for message in ("   ", "x" * 4001):
        assert (
            client.post(
                "/api/chat", headers=headers, json={"session_id": sid, "message": message}
            ).status_code
            == 422
        )
    assert (
        client.post(
            "/api/chat", headers=headers, json={"session_id": "bad", "message": "x"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/chat", headers=headers, json={"session_id": sid, "message": "x"}
        ).status_code
        == 200
    )


def test_history_pagination_and_legacy_session_exclusion(api):
    client, headers, book_id, _, factory, _ = api
    sid = session(api)
    with factory.begin() as db:
        db.add(ChatSession(book_id=uuid.UUID(book_id), grade="8", subject="العلوم"))
        for number in range(105):
            db.add(Message(session_id=uuid.UUID(sid), role="user", content=str(number)))
    assert len(client.get("/api/sessions", headers=headers).json()) == 1
    first = client.get(f"/api/sessions/{sid}/messages", headers=headers).json()
    assert len(first["messages"]) == 100
    assert first["has_more"]
    second = client.get(
        f"/api/sessions/{sid}/messages?before={first['next_before']}", headers=headers
    ).json()
    assert len(second["messages"]) == 5
    assert not second["has_more"]
    assert [m["content"] for m in second["messages"] + first["messages"]] == [
        str(n) for n in range(105)
    ]


def test_page_queries_and_msa_survive_integration(api, monkeypatch):
    client, headers, _, _, _, seen = api
    queries = []
    vector = [1.0] + [0.0] * (get_settings().embedding_dim - 1)

    def embed(self, values):
        queries.extend(values)
        return [vector for _ in values]

    monkeypatch.setattr(EmbeddingClient, "embed", embed)
    monkeypatch.setattr(get_settings(), "tutor_dialect", "msa")
    sid = session(api)
    response = client.post(
        "/api/chat", headers=headers, json={"session_id": sid, "message": "اشرح صفحة 15"}
    )
    assert events(response)[-1] == {"done": True}
    assert queries == ["اشرح صفحة 15", "القوة تؤثر على الحركة."]
    assert "الفصحى" in seen[-1][0]["content"]
    assert "مشكولاً بالكامل" in seen[-1][0]["content"]
    history = client.get(f"/api/sessions/{sid}/messages", headers=headers).json()
    assert history["messages"][-1]["sources"] == [{"page": 15, "section": "القوة"}]


def test_voice_auth_limits_and_vocalized_payloads(api, monkeypatch):
    client, headers, *_ = api
    calls = []

    def transcribe(audio, filename, content_type):
        calls.append((audio, filename, content_type))
        return "ما هي القوة؟"

    def synthesize(text, rate=None):
        calls.append((text, rate))
        return b"ID3test-audio"

    monkeypatch.setattr(main, "transcribe", transcribe)
    monkeypatch.setattr(main, "synthesize", synthesize)
    monkeypatch.setattr(get_settings(), "groq_api_key", "private-groq-test-key")
    monkeypatch.setattr(get_settings(), "azure_speech_key", "private-azure-test-key")
    monkeypatch.setattr(get_settings(), "azure_speech_region", "test-region")
    for path in ("/api/stt", "/api/tts"):
        assert client.post(path).status_code == 401
    assert client.get("/api/settings").status_code == 401
    settings = client.get("/api/settings", headers=headers)
    assert settings.json()["stt"] and settings.json()["tts"]
    assert "private-" not in settings.text
    response = client.post(
        "/api/stt", headers=headers, files={"file": ("clip.webm", b"x" * 500, "audio/webm")}
    )
    assert response.json() == {"text": "ما هي القوة؟"}
    assert calls[-1] == (b"x" * 500, "clip.webm", "audio/webm")
    count = len(calls)
    assert client.post(
        "/api/stt", headers=headers, files={"file": ("clip.webm", b"x" * 1500001)}
    ).status_code == 413
    assert len(calls) == count
    text = "القُوَّةُ تُؤَثِّرُ عَلَى الحَرَكَةِ."
    response = client.post("/api/tts", headers=headers, json={"text": text, "rate": "-25%"})
    assert response.content == b"ID3test-audio"
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["cache-control"] == "no-store"
    assert calls[-1] == (text, "-25%")
    count = len(calls)
    for payload in ({"text": "x" * 12001}, {"text": "x", "rate": '<bad>'}):
        assert client.post("/api/tts", headers=headers, json=payload).status_code == 422
    assert len(calls) == count


def test_speech_errors_are_safe_and_release_slots(api, monkeypatch):
    client, headers, *_ = api

    def fail(text, rate=None):
        raise main.TtsError("private-provider-key", 429)

    monkeypatch.setattr(main, "synthesize", fail)
    response = client.post("/api/tts", headers=headers, json={"text": "مرحبا"})
    assert response.status_code == 429
    assert "private-provider-key" not in response.text
    monkeypatch.setattr(main, "synthesize", lambda text, rate=None: b"audio")
    assert client.post("/api/tts", headers=headers, json={"text": "مرحبا"}).status_code == 200
