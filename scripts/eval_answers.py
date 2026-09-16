"""Score answer quality (grounded, dialect) and page-targeted retrieval."""

import json
import re
import uuid
from pathlib import Path

from ai_tutor.db import session_scope
from ai_tutor.memory import session as memory
from ai_tutor.openrouter import build_client
from ai_tutor.rag.retrieve import retrieve_by_pages
from ai_tutor.tutor.service import answer

EVAL = Path(__file__).resolve().parent.parent / "data" / "eval" / "grade8.json"
JUDGE_MODEL = "google/gemini-3.8-flash"

JUDGE_SYSTEM = (
    "أنت مقيّم صارم. عندك سؤال، ومقتطفات المصدر بأرقام صفحاتها، وجواب مدرّس. "
    "الجواب مسموح يضيف شرحًا عامًا من معرفته، لكن ممنوع: "
    "(1) يخالف المقتطفات، (2) ينسب للكتاب معلومة غير موجودة فيه، "
    "(3) يخترع رقم صفحة غير موجود في المقتطفات. "
    'أرجِع JSON فقط: {"grounded": true|false, "dialect": true|false, "reason": "..."} '
    "grounded = لا مخالفة ولا اختراع منسوب للكتاب (المعلومات العامة مسموحة). "
    "dialect = الجواب باللهجة الأردنية العامية بشكل طبيعي."
)


def parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(match.group(0)) if match else {}


def format_sources(chunks) -> str:
    parts = []
    for chunk in chunks:
        page = chunk.display_page
        label = f"[صفحة {page}]" if page else "[بدون رقم صفحة]"
        parts.append(f"{label}\n{chunk.content}")
    return "\n\n".join(parts)[:6000]


def main() -> None:
    items = json.loads(EVAL.read_text(encoding="utf-8"))
    client = build_client()
    result = {"grounded": 0, "dialect": 0, "page_ok": 0}
    failures = []
    page_total = 0

    with session_scope() as db:
        for item in items:
            book_id = uuid.UUID(item["book_id"])
            session = memory.create_session(
                db, grade="8", subject="", book_id=book_id, title=item["title"]
            )
            reply = answer(db, session=session, user_message=item["question"])
            excerpts = format_sources(reply.sources)

            judged = parse_json(
                client.post(
                    "/chat/completions",
                    json={
                        "model": JUDGE_MODEL,
                        "messages": [
                            {"role": "system", "content": JUDGE_SYSTEM},
                            {
                                "role": "user",
                                "content": (
                                    f"السؤال:\n{item['question']}\n\n"
                                    f"المقتطفات:\n{excerpts}\n\n"
                                    f"الجواب:\n{reply.text[:1500]}"
                                ),
                            },
                        ],
                        "temperature": 0,
                    },
                ).json()["choices"][0]["message"]["content"]
            )
            if judged.get("grounded"):
                result["grounded"] += 1
            if judged.get("dialect"):
                result["dialect"] += 1

            if item["printed_page"] is not None:
                page_total += 1
                page_chunks = retrieve_by_pages(
                    db, book_id=book_id, pages=[item["printed_page"]]
                )
                if item["physical_page"] in [c.page_start for c in page_chunks]:
                    result["page_ok"] += 1

            if not (judged.get("grounded") and judged.get("dialect")):
                failures.append(
                    f"{item['title'][:16]} p{item['physical_page']}: "
                    f"{judged.get('reason', '')[:120]}"
                )

    total = len(items)
    page_score = result["page_ok"] / page_total if page_total else 0.0
    print(
        f"n={total}  grounded={result['grounded'] / total:.3f}  "
        f"dialect={result['dialect'] / total:.3f}  "
        f"page_ok={page_score:.3f} (n={page_total})"
    )
    print(f"failures: {len(failures)}")
    for line in failures[:10]:
        print("  " + line)


if __name__ == "__main__":
    main()