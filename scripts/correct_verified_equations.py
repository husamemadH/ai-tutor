import argparse
import json
import math
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from ai_tutor.config import get_settings
from ai_tutor.db import session_scope
from ai_tutor.embeddings import EmbeddingClient
from ai_tutor.models import Book, Chunk

DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[1] / "data/corrections/2026-10-07-math-equations.json"
)


def corrected_content(content: str, old: str, new: str) -> str:
    if not old or not new or old == new:
        raise ValueError("Invalid correction")
    if old not in content and new in content:
        return content
    if content.count(old) != 1:
        raise ValueError("Expected exactly one occurrence of the verified incorrect formula")
    return content.replace(old, new, 1)


def plan_corrections(corrections: list[dict]) -> tuple[list[dict], int]:
    pending = []
    already_corrected = 0
    seen = set()
    with session_scope() as db:
        for correction in corrections:
            books = db.scalars(
                select(Book).where(
                    Book.title == correction["book_title"], Book.grade == correction["grade"]
                )
            ).all()
            if len(books) != 1:
                raise ValueError(f"Expected one matching book: {correction['book_title']}")
            page = correction["pdf_page"]
            chunks = db.scalars(
                select(Chunk).where(
                    Chunk.book_id == books[0].id,
                    Chunk.page_start <= page,
                    Chunk.page_end >= page,
                    Chunk.content.contains(correction["old"], autoescape=True)
                    | Chunk.content.contains(correction["new"], autoescape=True),
                )
            ).all()
            if not chunks:
                raise ValueError(f"Verified equation not found: {books[0].title}, page {page}")
            for chunk in chunks:
                new_content = corrected_content(chunk.content, correction["old"], correction["new"])
                if new_content == chunk.content:
                    already_corrected += 1
                    continue
                if chunk.id in seen:
                    raise ValueError("Multiple corrections target one chunk; combine them first")
                seen.add(chunk.id)
                pending.append(
                    {
                        "chunk_id": str(chunk.id),
                        "book_id": str(chunk.book_id),
                        "book_title": books[0].title,
                        "page_start": chunk.page_start,
                        "page_end": chunk.page_end,
                        "printed_page": chunk.printed_page,
                        "section": chunk.section,
                        "content": chunk.content,
                        "token_count": chunk.token_count,
                        "embedding": [float(value) for value in chunk.embedding],
                        "new_content": new_content,
                    }
                )
    return pending, already_corrected


def apply_corrections(pending: list[dict], backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = (
        backup_dir / f"chunks-before-{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}.json"
    )
    with backup.open("x") as file:
        backup.chmod(0o600)
        json.dump(pending, file, ensure_ascii=False, indent=2)
    vectors = []
    with EmbeddingClient() as embedder:
        for item in pending:
            vector = embedder.embed_one(item["new_content"])
            if len(vector) != get_settings().embedding_dim or not all(
                math.isfinite(v) for v in vector
            ):
                raise ValueError("Invalid corrected embedding")
            vectors.append(vector)
    with session_scope() as db:
        for item, vector in zip(pending, vectors, strict=True):
            chunk = db.get(Chunk, uuid.UUID(item["chunk_id"]), with_for_update=True)
            if chunk is None or any(
                (
                    chunk.content != item["content"],
                    str(chunk.book_id) != item["book_id"],
                    chunk.page_start != item["page_start"],
                    chunk.page_end != item["page_end"],
                    chunk.printed_page != item["printed_page"],
                    chunk.section != item["section"],
                )
            ):
                raise ValueError("Chunk changed after planning; no corrections committed")
            chunk.content = item["new_content"]
            chunk.token_count = max(1, len(chunk.content) // 4)
            chunk.embedding = vector
    return backup


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply only visually verified equation corrections."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--backup-dir", type=Path, default=Path("dist/textbook-corrections"))
    parser.add_argument(
        "--apply", action="store_true", help="Write corrections and new embeddings."
    )
    args = parser.parse_args()
    corrections = json.loads(args.manifest.read_text())
    pending, already_corrected = plan_corrections(corrections)
    for item in pending:
        print(f"{item['book_title']}, page {item['page_start']}: {item['chunk_id']}")
    result = {
        "pending_chunks": len(pending),
        "already_corrected": already_corrected,
        "applied": False,
    }
    if args.apply and pending:
        result["backup"] = str(apply_corrections(pending, args.backup_dir))
        result["applied"] = True
    print(json.dumps(result))


if __name__ == "__main__":
    main()
