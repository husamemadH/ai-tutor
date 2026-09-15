import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_tutor.models import Book


def list_books(db: Session) -> list[Book]:
    return list(db.scalars(select(Book).order_by(Book.created_at, Book.title)))


def find_book(db: Session, ref: str) -> Book | None:
    """Resolve a book by full UUID or by title substring."""
    try:
        book = db.get(Book, uuid.UUID(ref))
        if book is not None:
            return book
    except ValueError:
        pass
    stmt = select(Book).where(Book.title.ilike(f"%{ref}%")).limit(1)
    return db.scalars(stmt).first()