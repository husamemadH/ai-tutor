"""Multi-turn eval: context retention, bounded context, and answer quality."""

import json
import re

from sqlalchemy import select

from ai_tutor.books import list_books
from ai_tutor.db import session_scope
from ai_tutor.memory import session as memory
from ai_tutor.models import Chunk
from ai_tutor.openrouter import build_client
from ai_tutor.tutor.service import answer

JUDGE_MODEL = "google/gemini-3.8-flash"
MAX_CHUNKS = 15

TURNS = [
    "اشرحلي باختصار اللي في صفحة {page}",
    "وليش هالشي مهم؟",
    "أعطيني مثال من الحياة",
    "لخّصلي الفكرة بجملة",
]

JUDGE_SYSTEM = (
    "أنت مقيّم صارم. عندك سؤال، ومقتطفات المصدر، وجواب مدرّس. "
    'أرجِع JSON فقط: {"grounded": true|false, "dialect": true|false} '
    "grounded = لا مخالفة للمقتطفات ولا اختراع منسوب للكتاب (المعلومات العامة مسموحة). "
    "dialect = الجواب باللهجة الأردنية العامية بشكل طبيعي."
)


def parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(match.group(0)) if match else {}


def pick_page(chunks: list[Chunk]) -> Chunk | None:
    candidates = [c for c in chunks if c.printed_page and len(c.content) > 500]
    candidates.sort(key=lambda c: c.page_start or 0)
    return candidates[len(candidates) // 2] if candidates else None


def judge(client, question: str, excerpts: str, reply: str) -> dict:
    response = client.post(
        "/chat/completions",
        json={
            "model": JUDGE_MODEL,
            "messages": [
                {"role": "system", "content": JUDGE_SYSTEM},
                {
                    "role": "user",
                    "content": f"السؤال:\n{question}\n\nالمقتطفات:\n{excerpts}\n\nالجواب:\n{reply}",
                },
            ],
            "temperature": 0,
        },
    )
    return parse_json(response.json()["choices"][0]["message"]["content"])


def main() -> None:
    client = build_client()
    retention_hits = retention_total = 0
    max_chunks = 0
    grounded = dialect = judged = 0

    with session_scope() as db:
        books = [b for b in list_books(db) if b.grade == "8"]
        for book in books:
            chunks = list(db.scalars(select(Chunk).where(Chunk.book_id == book.id)))
            page = pick_page(chunks)
            if page is None:
                continue
            session = memory.create_session(
                db, grade=book.grade, subject=book.subject, book_id=book.id, title=book.title
            )
            for index, template in enumerate(TURNS):
                message = template.format(page=page.printed_page)
                reply = answer(db, session=session, user_message=message)
                max_chunks = max(max_chunks, len(reply.sources))
                pages = [c.display_page for c in reply.sources]
                if index > 0:
                    retention_total += 1
                    if page.printed_page in pages:
                        retention_hits += 1
                if index == 1:
                    excerpts = "\n".join(
                        f"[صفحة {c.display_page}]\n{c.content}" for c in reply.sources
                    )[:6000]
                    verdict = judge(client, message, excerpts, reply.text[:1500])
                    judged += 1
                    grounded += bool(verdict.get("grounded"))
                    dialect += bool(verdict.get("dialect"))
            print(f"{book.subject:10s} target page {page.printed_page} done")

    retention = retention_hits / retention_total if retention_total else 0.0
    print(
        f"\ncontext_retention={retention:.3f}  max_chunks={max_chunks} "
        f"(cap {MAX_CHUNKS})  grounded={grounded / max(1, judged):.3f}  "
        f"dialect={dialect / max(1, judged):.3f}  conversations={judged}"
    )


if __name__ == "__main__":
    main()