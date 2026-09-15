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
    """Fetch chunks overlapping any of the given page numbers, in page order."""
    if book_id is None or not pages:
        return []
    overlaps = [
        and_(Chunk.page_start <= page, Chunk.page_end >= page) for page in set(pages)
    ]
    stmt = (
        select(Chunk)
        .where(Chunk.book_id == book_id, or_(*overlaps))
        .order_by(Chunk.page_start)
    )
    return list(db.scalars(stmt))