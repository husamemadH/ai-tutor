import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_tutor.models import ChatSession, Message


def create_session(
    db: Session,
    *,
    grade: str,
    subject: str,
    book_id: uuid.UUID | None = None,
    title: str | None = None,
) -> ChatSession:
    session = ChatSession(grade=grade, subject=subject, book_id=book_id, title=title)
    db.add(session)
    db.flush()
    return session


def get_session(db: Session, session_id: uuid.UUID) -> ChatSession | None:
    return db.get(ChatSession, session_id)


def get_context(db: Session, session_id: uuid.UUID, limit: int) -> list[Message]:
    """Last `limit` messages, oldest first. The single seam for future summarization."""
    stmt = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.seq.desc())
        .limit(limit)
    )
    return list(reversed(list(db.scalars(stmt))))


def append_message(
    db: Session,
    session_id: uuid.UUID,
    role: str,
    content: str,
    source_chunk_ids: list[str] | None = None,
    source_metadata: list[dict] | None = None,
) -> Message:
    message = Message(
        session_id=session_id,
        role=role,
        content=content,
        source_chunk_ids=source_chunk_ids,
        source_metadata=source_metadata,
    )
    db.add(message)
    db.flush()
    return message
