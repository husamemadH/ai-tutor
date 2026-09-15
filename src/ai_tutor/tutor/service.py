import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ai_tutor.config import get_settings
from ai_tutor.embeddings import EmbeddingClient
from ai_tutor.llm import ChatClient
from ai_tutor.memory import session as memory
from ai_tutor.models import Book, ChatSession, Chunk, Message
from ai_tutor.rag.retrieve import retrieve, retrieve_by_pages
from ai_tutor.tutor.prompt import build_system_prompt


@dataclass
class TutorReply:
    text: str
    sources: list[Chunk] = field(default_factory=list)


@dataclass
class StreamEvent:
    """Streaming turn output: sources once, then text deltas."""

    delta: str | None = None
    sources: list[Chunk] | None = None


_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_PAGE_HINT = re.compile(r"صفح(?:ة|ات|ت)?\s*\.?\s*((?:\d+[\s،,و-]*)+)", re.IGNORECASE)
_FOLLOWUP_START = re.compile(
    r"^(?:ليش|ليه|طب|طيب|وبعدين|بعدين|وضّ?ح|اشرح|أكثر|اكثر|كمان|نفس|يعني)\b"
)
_ANAPHORA = re.compile(
    r"\b(?:هي|هو|هاد|هاي|هذه|هذا|هم|هن|بينهم|عنهم|عنو|عنها|إله|إلها|مالو|نفسه|نفسها)\b"
)


def extract_pages(text: str) -> list[int]:
    """Pull explicit page references like 'صفحة 31' or 'صفحات 14 و 15' from a message."""
    normalized = text.translate(_ARABIC_DIGITS)
    pages: set[int] = set()
    for match in _PAGE_HINT.finditer(normalized):
        pages.update(int(number) for number in re.findall(r"\d+", match.group(1)))
    return sorted(pages)


def _is_followup(message: str) -> bool:
    """True for short/anaphoric messages that only make sense with prior context."""
    text = message.strip()
    return (
        len(text) <= 12
        or bool(_FOLLOWUP_START.search(text))
        or bool(_ANAPHORA.search(text))
    )


def _retrieval_query(history: list[Message], user_message: str) -> str:
    """Use recent turns only for genuine follow-ups, so new topics aren't polluted."""
    if history and _is_followup(user_message):
        tail = [message.content for message in history[-2:]]
        return "\n".join([*tail, user_message])
    return user_message


def _dedupe(chunks: list[Chunk]) -> list[Chunk]:
    seen: set = set()
    result: list[Chunk] = []
    for chunk in chunks:
        if chunk.id not in seen:
            seen.add(chunk.id)
            result.append(chunk)
    return result


def _prepare(
    db: Session,
    *,
    session: ChatSession,
    user_message: str,
    top_k: int | None,
    page: int | None,
) -> tuple[list[dict[str, str]], list[Chunk]]:
    """Retrieve context and build the message list for one turn."""
    settings = get_settings()
    history = memory.get_context(db, session.id, settings.memory_window_turns)

    pages = set(extract_pages(user_message))
    if page is not None:
        pages.add(page)

    chunks: list[Chunk] = []
    if session.book_id is not None:
        query_vector = EmbeddingClient().embed_one(_retrieval_query(history, user_message))
        semantic = retrieve(
            db,
            query_embedding=query_vector,
            book_id=session.book_id,
            top_k=top_k or settings.retrieval_top_k,
        )
        page_chunks = retrieve_by_pages(db, book_id=session.book_id, pages=sorted(pages))
        chunks = _dedupe([*page_chunks, *semantic])

    book = db.get(Book, session.book_id) if session.book_id else None
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": build_system_prompt(
                grade=session.grade,
                subject=session.subject,
                book_title=book.title if book else None,
                chunks=chunks,
            ),
        }
    ]
    messages += [{"role": message.role, "content": message.content} for message in history]
    messages.append({"role": "user", "content": user_message})
    return messages, chunks


def answer(
    db: Session,
    *,
    session: ChatSession,
    user_message: str,
    top_k: int | None = None,
    page: int | None = None,
) -> TutorReply:
    messages, chunks = _prepare(
        db, session=session, user_message=user_message, top_k=top_k, page=page
    )
    text = ChatClient().complete(messages)
    memory.append_message(db, session.id, "user", user_message)
    memory.append_message(db, session.id, "assistant", text)
    return TutorReply(text=text, sources=chunks)


def answer_stream(
    db: Session,
    *,
    session: ChatSession,
    user_message: str,
    top_k: int | None = None,
    page: int | None = None,
) -> Iterator[StreamEvent]:
    """Yield sources once, then text deltas; persist the turn when finished."""
    messages, chunks = _prepare(
        db, session=session, user_message=user_message, top_k=top_k, page=page
    )
    yield StreamEvent(sources=chunks)

    parts: list[str] = []
    for delta in ChatClient().stream(messages):
        parts.append(delta)
        yield StreamEvent(delta=delta)

    text = "".join(parts)
    memory.append_message(db, session.id, "user", user_message)
    memory.append_message(db, session.id, "assistant", text)