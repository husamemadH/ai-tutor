from itertools import batched
from pathlib import Path

from sqlalchemy.orm import Session

from ai_tutor.embeddings import EmbeddingClient
from ai_tutor.ingest.chunk import TextChunk, chunk_pages
from ai_tutor.ingest.ocr import OcrClient
from ai_tutor.ingest.parse import Page, parse_pdf
from ai_tutor.models import Book, Chunk


def _token_count(text: str) -> int:
    return max(1, len(text) // 4)


def ingest_pages(
    db: Session,
    *,
    pages: list[Page],
    grade: str,
    subject: str,
    title: str,
    file_path: str,
    batch_size: int = 64,
) -> tuple[Book, int]:
    """Chunk -> embed -> store already-parsed pages. Returns book and chunk count."""
    text_chunks: list[TextChunk] = chunk_pages(pages)
    if not text_chunks:
        raise ValueError(f"No extractable text found for '{title}'")

    book = Book(
        title=title,
        grade=grade,
        subject=subject,
        language="ar",
        file_path=file_path,
    )
    db.add(book)
    db.flush()

    embedder = EmbeddingClient()
    for batch in batched(text_chunks, batch_size):
        vectors = embedder.embed([chunk.content for chunk in batch])
        for chunk, vector in zip(batch, vectors, strict=True):
            content = chunk.content
            printed = next(
                (p.printed_number for p in pages if p.number == chunk.page_start), None
            )
            db.add(
                Chunk(
                    book_id=book.id,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    printed_page=printed,
                    section=chunk.section,
                    content=content,
                    token_count=_token_count(content),
                    embedding=vector,
                )
            )
        db.flush()

    db.commit()
    return book, len(text_chunks)


def ingest_book(
    db: Session,
    *,
    pdf_path: Path,
    grade: str,
    subject: str,
    title: str | None = None,
    batch_size: int = 64,
    ocr: bool = True,
) -> tuple[Book, int]:
    """OCR (default) or text-layer parse, then chunk -> embed -> store."""
    pages = OcrClient().ocr_pdf(pdf_path) if ocr else parse_pdf(pdf_path)
    return ingest_pages(
        db,
        pages=pages,
        grade=grade,
        subject=subject,
        title=title or pdf_path.stem,
        file_path=str(pdf_path),
        batch_size=batch_size,
    )