import json
import logging
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Annotated

import anyio
import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from ai_tutor.api.auth import Identity, normalize_grade, require_identity
from ai_tutor.books import list_books
from ai_tutor.config import get_settings
from ai_tutor.db import SessionLocal, engine, session_scope
from ai_tutor.models import Book, ChatSession, Message
from ai_tutor.openrouter import generation_deadline
from ai_tutor.stt import MAX_AUDIO_BYTES, SttError, transcribe
from ai_tutor.tts import TtsError, synthesize
from ai_tutor.tutor.service import answer_stream

app = FastAPI(title="AI Tutor", version="0.2.0")
logger = logging.getLogger(__name__)
slots = threading.BoundedSemaphore(max(1, get_settings().tutor_max_concurrent))


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    logger.warning("Tutor database operation failed")
    return JSONResponse({"detail": "Tutor database is unavailable"}, status_code=503)


@app.get("/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT student_id, tenant_id FROM sessions LIMIT 0"))
            conn.execute(text("SELECT source_metadata FROM messages LIMIT 0"))
        return {"status": "ok", "database": True}
    except SQLAlchemyError:
        return JSONResponse({"status": "degraded", "database": False}, status_code=503)


class BookOut(BaseModel):
    id: str
    title: str
    grade: str
    subject: str


class SessionIn(BaseModel):
    book_id: uuid.UUID


class ChatIn(BaseModel):
    session_id: uuid.UUID
    message: str = Field(min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message cannot be empty")
        return value


def owned_session(db, session_id: uuid.UUID, identity: Identity) -> ChatSession:
    session = db.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.student_id == identity.student_id,
            ChatSession.tenant_id == identity.tenant_id,
        )
    )
    if session is None:
        raise HTTPException(404, "Conversation not found")
    book = db.get(Book, session.book_id) if session.book_id else None
    if book is None or normalize_grade(book.grade) != identity.grade:
        raise HTTPException(403, "Textbook is unavailable for this grade")
    return session


def session_out(session: ChatSession) -> dict:
    return {
        "session_id": str(session.id),
        "book_id": str(session.book_id),
        "title": session.title,
        "created_at": session.created_at.isoformat(),
    }


@app.get("/api/books")
def get_books(identity: Annotated[Identity, Depends(require_identity)]) -> list[BookOut]:
    with session_scope() as db:
        return [
            BookOut(id=str(book.id), title=book.title, grade=book.grade, subject=book.subject)
            for book in list_books(db)
            if normalize_grade(book.grade) == identity.grade
        ]


@app.post("/api/sessions", status_code=201)
def create_session(
    payload: SessionIn, identity: Annotated[Identity, Depends(require_identity)]
) -> dict:
    with session_scope() as db:
        book = db.get(Book, payload.book_id)
        if book is None or normalize_grade(book.grade) != identity.grade:
            raise HTTPException(404, "Textbook not found for this grade")
        session = ChatSession(
            book_id=book.id,
            grade=book.grade,
            subject=book.subject,
            title=book.title,
            student_id=identity.student_id,
            tenant_id=identity.tenant_id,
        )
        db.add(session)
        db.flush()
        return session_out(session)


@app.get("/api/sessions")
def get_sessions(identity: Annotated[Identity, Depends(require_identity)]) -> list[dict]:
    with session_scope() as db:
        sessions = db.execute(
            select(ChatSession, Book)
            .join(Book, Book.id == ChatSession.book_id)
            .where(
                ChatSession.student_id == identity.student_id,
                ChatSession.tenant_id == identity.tenant_id,
            )
            .order_by(ChatSession.created_at.desc(), ChatSession.id.desc())
            .limit(100)
        )
        return [
            session_out(s) for s, book in sessions if normalize_grade(book.grade) == identity.grade
        ]


@app.get("/api/sessions/{session_id}/messages")
def get_messages(
    session_id: uuid.UUID,
    identity: Annotated[Identity, Depends(require_identity)],
    before: Annotated[int | None, Query(gt=0)] = None,
) -> dict:
    with session_scope() as db:
        session = owned_session(db, session_id, identity)
        stmt = select(Message).where(Message.session_id == session.id)
        if before is not None:
            stmt = stmt.where(Message.seq < before)
        messages = list(db.scalars(stmt.order_by(Message.seq.desc()).limit(101)))
        has_more = len(messages) > 100
        messages = list(reversed(messages[:100]))
        return {
            "session": session_out(session),
            "messages": [
                {
                    "id": str(m.id),
                    "seq": m.seq,
                    "role": m.role,
                    "content": m.content,
                    "sources": m.source_metadata or [],
                }
                for m in messages
            ],
            "has_more": has_more,
            "next_before": messages[0].seq if has_more else None,
        }


def event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def next_item(iterator: Iterator):
    return next(iterator, None)


@app.post("/api/chat")
def chat(
    payload: ChatIn, identity: Annotated[Identity, Depends(require_identity)]
) -> StreamingResponse:
    if not slots.acquire(blocking=False):
        raise HTTPException(429, "Tutor is busy. Try again shortly")
    db = SessionLocal()
    try:
        session = owned_session(db, payload.session_id, identity)
        locked = db.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"),
            {"key": int.from_bytes(payload.session_id.bytes[:8], "big", signed=True)},
        )
        if not locked:
            raise HTTPException(409, "A reply is already being generated for this conversation")
        db.refresh(session)
    except Exception:
        db.close()
        slots.release()
        raise

    iterator = answer_stream(db, session=session, user_message=payload.message)
    started = time.monotonic()
    closed = False
    cleanup_lock = threading.Lock()

    def cleanup():
        nonlocal closed
        with cleanup_lock:
            if closed:
                return
            closed = True
            try:
                iterator.close()
            finally:
                try:
                    db.close()
                finally:
                    slots.release()

    async def generate():
        deadline_token = generation_deadline.set(started + get_settings().tutor_generation_timeout)
        try:
            while True:
                item = await run_in_threadpool(next_item, iterator)
                if time.monotonic() - started > get_settings().tutor_generation_timeout:
                    raise TimeoutError("Generation deadline exceeded")
                if item is None:
                    await run_in_threadpool(db.commit)
                    yield event({"done": True})
                    break
                if item.sources is not None:
                    yield event(
                        {
                            "sources": [
                                {"page": c.display_page, "section": c.section} for c in item.sources
                            ]
                        }
                    )
                if item.delta:
                    yield event({"delta": item.delta})
        except (SQLAlchemyError, RuntimeError, httpx.HTTPError, TimeoutError, ValueError, KeyError):
            logger.warning("Tutor generation failed for session %s", payload.session_id)
            yield event({"error": "تعذر إكمال الإجابة. يرجى المحاولة لاحقاً."})
        finally:
            generation_deadline.reset(deadline_token)
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(cleanup)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        background=BackgroundTask(cleanup),
    )


@app.get("/api/settings")
def tutor_settings(identity: Annotated[Identity, Depends(require_identity)]) -> dict:
    settings = get_settings()
    return {
        "dialect": settings.tutor_dialect,
        "stt": bool(settings.groq_api_key),
        "tts": bool(settings.azure_speech_key and settings.azure_speech_region),
        "max_recording_seconds": settings.stt_max_seconds,
        "tts_rate": settings.azure_tts_rate,
    }


class SttOut(BaseModel):
    text: str


@app.post("/api/stt")
def speech_to_text(
    identity: Annotated[Identity, Depends(require_identity)],
    file: Annotated[UploadFile, File()],
) -> SttOut:
    if not slots.acquire(blocking=False):
        raise HTTPException(429, "Tutor is busy. Try again shortly")
    try:
        audio = file.file.read(MAX_AUDIO_BYTES + 1)
        if len(audio) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "Audio too long")
        transcript = transcribe(audio, file.filename or "clip.webm", file.content_type)
        return SttOut(text=transcript)
    except SttError as exc:
        raise HTTPException(exc.status_code, "Speech transcription unavailable") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Speech service failed") from exc
    finally:
        file.file.close()
        slots.release()


class TtsIn(BaseModel):
    text: str = Field(min_length=1, max_length=12000)
    rate: str | None = Field(default=None, pattern=r"^(?:[+-]?\d{1,3}%|x-slow|slow|medium|fast|x-fast)$")


@app.post("/api/tts")
def text_to_speech(
    payload: TtsIn, identity: Annotated[Identity, Depends(require_identity)]
) -> Response:
    if not slots.acquire(blocking=False):
        raise HTTPException(429, "Tutor is busy. Try again shortly")
    try:
        audio = synthesize(payload.text, rate=payload.rate)
        return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})
    except TtsError as exc:
        raise HTTPException(exc.status_code, "Speech synthesis unavailable") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Speech service failed") from exc
    finally:
        slots.release()
