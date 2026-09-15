from ai_tutor.ingest.chunk import chunk_pages, normalize_arabic
from ai_tutor.ingest.parse import Page


def test_normalize_strips_diacritics_and_tatweel():
    assert normalize_arabic("مُحَمَّدٌ") == "محمد"
    assert normalize_arabic("كتـــاب") == "كتاب"


def test_headings_start_new_sections():
    pages = [
        Page(1, "الخلية\n\nالخلية هي وحدة البناء الأساسية."),
        Page(2, "النواة\n\n" + "النواة تتحكم بجميع أنشطة الخلية. " * 40),
    ]
    chunks = chunk_pages(pages, max_chars=300, overlap_chars=40)
    sections = [chunk.section for chunk in chunks]
    assert "الخلية" in sections
    assert "النواة" in sections


def test_page_span_is_tracked():
    pages = [Page(3, "فقرة أولى.\n\nفقرة ثانية.\n\nفقرة ثالثة.")]
    chunks = chunk_pages(pages, max_chars=1000)
    assert len(chunks) == 1
    assert chunks[0].page_start == 3
    assert chunks[0].page_end == 3


def test_long_text_splits_within_max_chars():
    pages = [Page(1, "\n\n".join("جملة رقم " + str(i) + " في هذا النص." for i in range(80)))]
    chunks = chunk_pages(pages, max_chars=200, overlap_chars=20)
    assert len(chunks) > 1
    assert all(len(chunk.content) <= 300 for chunk in chunks)