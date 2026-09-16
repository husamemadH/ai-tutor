"""Generate a held-out eval set from ingested books: one question per sampled page."""

import json
from pathlib import Path

from sqlalchemy import select

from ai_tutor.books import list_books
from ai_tutor.db import session_scope
from ai_tutor.llm import ChatClient
from ai_tutor.models import Chunk

PER_BOOK = 10
OUT = Path(__file__).resolve().parent.parent / "data" / "eval" / "grade8.json"

SYSTEM = (
    "اكتب سؤالًا واحدًا بالعربية يجيب عنه النص التالي، من وجهة نظر طالب مدرسة. "
    "أخرج السؤال فقط في سطر واحد، بلا أي مقدمة أو شرح."
)


def pick(chunks: list[Chunk], n: int) -> list[Chunk]:
    chunks = [c for c in chunks if c.page_start and len(c.content) > 300]
    chunks.sort(key=lambda c: c.page_start or 0)
    if len(chunks) <= n:
        return chunks
    step = len(chunks) / n
    return [chunks[int(i * step)] for i in range(n)]


def main() -> None:
    client = ChatClient()
    items = []
    with session_scope() as db:
        for book in [b for b in list_books(db) if b.grade == "8"]:
            chunks = list(db.scalars(select(Chunk).where(Chunk.book_id == book.id)))
            for chunk in pick(chunks, PER_BOOK):
                question = client.complete(
                    [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": chunk.content[:1500]},
                    ],
                    temperature=0.5,
                ).strip()
                items.append(
                    {
                        "book_id": str(book.id),
                        "title": book.title,
                        "physical_page": chunk.page_start,
                        "printed_page": chunk.printed_page,
                        "question": question.splitlines()[0],
                    }
                )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(items)} questions to {OUT}")


if __name__ == "__main__":
    main()