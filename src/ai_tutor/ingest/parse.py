from dataclasses import dataclass
from pathlib import Path

import pymupdf


@dataclass
class Page:
    number: int
    text: str


def parse_pdf(path: Path) -> list[Page]:
    """Extract raw text from each page of a PDF (1-based page numbers)."""
    pages: list[Page] = []
    with pymupdf.open(path) as doc:
        for index, page in enumerate(doc, start=1):
            pages.append(Page(number=index, text=page.get_text("text")))
    return pages