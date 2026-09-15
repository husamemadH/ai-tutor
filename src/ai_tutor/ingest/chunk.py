import re
from collections.abc import Iterable
from dataclasses import dataclass

from ai_tutor.ingest.parse import Page

_ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
_TATWEEL = "\u0640"
_MULTISPACE = re.compile(r"[ \t]+")
_MULTINEWLINE = re.compile(r"\n{3,}")
_SENTENCE_END = (".", "!", "?", "؟", "۔", ":", "؛", "،")


def normalize_arabic(text: str) -> str:
    """Strip diacritics/tatweel and collapse whitespace so variants match."""
    text = text.replace(_TATWEEL, "")
    text = _ARABIC_DIACRITICS.sub("", text)
    text = _MULTISPACE.sub(" ", text)
    text = _MULTINEWLINE.sub("\n\n", text)
    return text.strip()


@dataclass
class TextChunk:
    content: str
    page_start: int
    page_end: int
    section: str | None


def _looks_like_heading(paragraph: str) -> bool:
    lines = paragraph.splitlines()
    if len(lines) != 1:
        return False
    line = lines[0].strip()
    if not line or len(line) > 60 or len(line.split()) > 8:
        return False
    return not line.endswith(_SENTENCE_END)


def chunk_pages(
    pages: Iterable[Page],
    *,
    max_chars: int = 1200,
    overlap_chars: int = 150,
) -> list[TextChunk]:
    """Group normalized paragraphs into chunks, tracking page span and section."""
    chunks: list[TextChunk] = []
    buf: list[str] = []
    buf_len = 0
    page_start: int | None = None
    page_end: int | None = None
    section: str | None = None

    def flush(*, overlap: bool = True) -> None:
        nonlocal buf, buf_len, page_start, page_end
        if not buf or page_start is None:
            buf, buf_len, page_start, page_end = [], 0, None, None
            return
        content = "\n".join(buf).strip()
        if content:
            chunks.append(
                TextChunk(
                    content=content,
                    page_start=page_start,
                    page_end=page_end or page_start,
                    section=section,
                )
            )
        if overlap and overlap_chars > 0 and content:
            tail = content[-overlap_chars:]
            buf, buf_len = [tail], len(tail)
            page_start = page_end
        else:
            buf, buf_len, page_start = [], 0, None
        page_end = None

    current_page: int | None = None
    for page in pages:
        text = normalize_arabic(page.text)
        if not text:
            continue
        if buf and current_page is not None and page.number != current_page:
            flush(overlap=False)
        current_page = page.number
        for paragraph in (p.strip() for p in text.split("\n\n")):
            if not paragraph:
                continue
            if _looks_like_heading(paragraph):
                flush(overlap=False)
                section = paragraph
                page_start = page.number
            elif buf_len and buf_len + len(paragraph) > max_chars:
                flush()
                if page_start is None:
                    page_start = page.number
            elif page_start is None:
                page_start = page.number
            buf.append(paragraph)
            buf_len += len(paragraph)
            page_end = page.number

    flush()
    return chunks