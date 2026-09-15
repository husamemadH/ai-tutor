from ai_tutor.ingest.chunk import chunk_pages
from ai_tutor.ingest.parse import Page
from ai_tutor.tutor.service import extract_pages


def test_extract_pages_western_and_arabic_digits():
    assert extract_pages("بدي إشرح اللي في صفحة 31") == [31]
    assert extract_pages("صفحات 14 و 15") == [14, 15]
    assert extract_pages("الصفحة ٧") == [7]
    assert extract_pages("شو تأثير القوة؟") == []


def test_chunks_do_not_cross_page_boundaries():
    pages = [
        Page(10, "فقرة في الصفحة عشرة."),
        Page(11, "فقرة في الصفحة أحد عشر."),
    ]
    chunks = chunk_pages(pages, max_chars=1000, overlap_chars=150)
    assert [(c.page_start, c.page_end) for c in chunks] == [(10, 10), (11, 11)]