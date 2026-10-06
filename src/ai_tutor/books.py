import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_tutor.models import Book

_SUBJECT_NAMES = {
    "math": "رياضيات",
    "الرياضيات": "رياضيات",
    "رياضيات": "رياضيات",
    "science": "علوم",
    "العلوم": "علوم",
    "علوم": "علوم",
    "arabic": "اللغة العربية",
    "العربية": "اللغة العربية",
    "اللغة العربية": "اللغة العربية",
    "geo": "جغرافيا",
    "الجغرافيا": "جغرافيا",
    "physics": "فيزياء",
    "الفيزياء": "فيزياء",
    "chemistry": "كيمياء",
    "الكيمياء": "كيمياء",
    "lifescience": "علوم الحياة",
    "علوم الحياة": "علوم الحياة",
}


def display_book_title(book: Book) -> str:
    title = book.title.strip()
    code = re.fullmatch(r"([a-z]+)(\d+)", title, re.IGNORECASE)
    if code:
        subject = _SUBJECT_NAMES.get(code.group(1).lower())
        for number, semester in (("1", "الأول"), ("2", "الثاني")):
            if subject and code.group(2) == f"{book.grade}{number}":
                return f"{subject} - الفصل {semester}"
    semester = re.search(r"الفصل\s+(الأول|الثاني)", title)
    subject = _SUBJECT_NAMES.get(book.subject.strip().lower())
    prefix = re.split(r"\s*[-–—]\s*", title, maxsplit=1)[0]
    if semester and subject and _SUBJECT_NAMES.get(prefix) == subject:
        return f"{subject} - الفصل {semester.group(1)}"
    return book.title


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
