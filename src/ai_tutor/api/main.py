import json
import uuid
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ai_tutor.books import list_books
from ai_tutor.db import engine, session_scope
from ai_tutor.memory import session as memory
from ai_tutor.models import Book
from ai_tutor.stt import SttError, transcribe
from ai_tutor.tts import TtsError, synthesize
from ai_tutor.tutor.service import answer_stream

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="AI Tutor", version="0.1.0")


@app.get("/health")
def health() -> dict:
    database = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        database = True
    except SQLAlchemyError:
        database = False
    return {"status": "ok" if database else "degraded", "database": database}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


class BookOut(BaseModel):
    id: str
    title: str
    grade: str
    subject: str


@app.get("/api/books")
def get_books() -> list[BookOut]:
    with session_scope() as db:
        return [
            BookOut(id=str(book.id), title=book.title, grade=book.grade, subject=book.subject)
            for book in list_books(db)
        ]


class SessionIn(BaseModel):
    book_id: str | None = None
    grade: str = "غير محدد"
    subject: str = "عام"


class SessionOut(BaseModel):
    session_id: str
    title: str | None = None


@app.post("/api/sessions")
def create_session(payload: SessionIn) -> SessionOut:
    with session_scope() as db:
        book = None
        if payload.book_id:
            try:
                book = db.get(Book, uuid.UUID(payload.book_id))
            except ValueError:
                book = None
            if book is None:
                raise HTTPException(status_code=404, detail="Book not found")
        session = memory.create_session(
            db,
            grade=book.grade if book else payload.grade,
            subject=book.subject if book else payload.subject,
            book_id=book.id if book else None,
            title=book.title if book else None,
        )
        return SessionOut(session_id=str(session.id), title=session.title)


class SttOut(BaseModel):
    text: str


@app.post("/api/stt")
def speech_to_text(file: Annotated[UploadFile, File()]) -> SttOut:
    audio = file.file.read()
    try:
        text = transcribe(audio, file.filename or "clip.webm", file.content_type)
    except SttError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Speech service failed") from exc
    return SttOut(text=text)


class TtsIn(BaseModel):
    text: str
    rate: str | None = None


@app.post("/api/tts")
def text_to_speech(payload: TtsIn) -> Response:
    try:
        audio = synthesize(payload.text, rate=payload.rate)
    except TtsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Speech service failed") from exc
    return Response(content=audio, media_type="audio/mpeg")


class ChatIn(BaseModel):
    session_id: str
    message: str


def _event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/api/chat")
def chat(payload: ChatIn) -> StreamingResponse:
    try:
        session_uuid = uuid.UUID(payload.session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session id") from None

    def generate():
        try:
            with session_scope() as db:
                chat_session = memory.get_session(db, session_uuid)
                if chat_session is None:
                    yield _event({"error": "Session not found"})
                    return
                for event in answer_stream(
                    db, session=chat_session, user_message=payload.message
                ):
                    if event.sources is not None:
                        yield _event(
                            {
                                "sources": [
                                    {"page": chunk.display_page, "section": chunk.section}
                                    for chunk in event.sources
                                ]
                            }
                        )
                    if event.delta:
                        yield _event({"delta": event.delta})
            yield _event({"done": True})
        except (SQLAlchemyError, RuntimeError, httpx.HTTPError) as exc:
            yield _event({"error": str(exc)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )