"""Score retrieval against the held-out eval set: recall@k and MRR."""

import json
import uuid
from pathlib import Path

from ai_tutor.db import session_scope
from ai_tutor.embeddings import EmbeddingClient
from ai_tutor.rag.retrieve import retrieve

EVAL = Path(__file__).resolve().parent.parent / "data" / "eval" / "grade8.json"
TOP_K = 6


def main() -> None:
    items = json.loads(EVAL.read_text(encoding="utf-8"))
    embedder = EmbeddingClient()
    hits = 0
    mrr = 0.0
    misses = []
    with session_scope() as db:
        for item in items:
            vector = embedder.embed_one(item["question"])
            chunks = retrieve(
                db,
                query_embedding=vector,
                book_id=uuid.UUID(item["book_id"]),
                top_k=TOP_K,
            )
            pages = [c.page_start for c in chunks]
            if item["physical_page"] in pages:
                hits += 1
                mrr += 1.0 / (pages.index(item["physical_page"]) + 1)
            else:
                misses.append((item["title"][:18], item["physical_page"], pages))
    total = len(items)
    print(f"n={total}  recall@{TOP_K}={hits / total:.3f}  MRR={mrr / total:.3f}")
    print(f"misses: {len(misses)}")
    for title, target, got in misses:
        print(f"  {title} target p{target} -> got {got}")


if __name__ == "__main__":
    main()