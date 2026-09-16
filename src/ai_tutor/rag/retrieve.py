import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ai_tutor.models import Chunk


def retrieve(
    db: Session,
    *,
    query_embedding: list[float],
    book_id: uuid.UUID | None,
    top_k: int,
) -> list[Chunk]:
    """Cosine-similarity search scoped to a single book."""
    if book_id is None or top_k <= 0:
        return []
    stmt = (
        select(Chunk)
        .where(Chunk.book_id == book_id)
        .order_by(Chunk.embedding.cosine_distance(query_embedding))
        .limit(top_k)
    )
    return list(db.scalars(stmt))


def retrieve_by_pages(
    db: Session,
    *,
    book_id: uuid.UUID | None,
    pages: list[int],
) -> list[Chunk]:
    """Fetch chunks matching given printed page numbers, falling back to physical pages."""
    if book_id is None or not pages:
        return []
    matches = []
    for page in set(pages):
        matches.append(Chunk.printed_page == page)
        matches.append(and_(Chunk.page_start <= page, Chunk.page_end >= page))
    stmt = (
        select(Chunk)
        .where(Chunk.book_id == book_id, or_(*matches))
        .order_by(Chunk.page_start)
    )
    return list(db.scalars(stmt))