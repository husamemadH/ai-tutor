"""Generate a small Arabic sample textbook PDF for end-to-end testing."""

from pathlib import Path

import pymupdf

FONT = "/usr/share/fonts/noto/NotoNaskhArabic-Regular.ttf"

PAGES = [
    """
    <h2>الخلية</h2>
    <p>الخلية هي وحدة البناء الأساسية في جميع الكائنات الحية. تحتوي الخلية على غشاء
    يحيط بها ويحمي محتوياتها. داخل الخلية توجد أجزاء صغيرة تقوم بوظائف مختلفة.</p>
    <p>الخلية النباتية تختلف عن الخلية الحيوانية، لأن الخلية النباتية تحتوي على
    البلاستيدات الخضراء التي تساعد النبات على صنع غذائه.</p>
    <h2>النواة</h2>
    <p>النواة هي مركز التحكم في الخلية. تحتوي النواة على المادة الوراثية التي
    تحمل صفات الكائن الحي. النواة تتحكم بجميع أنشطة الخلية ووظائفها.</p>
    """,
    """
    <h2>البناء الضوئي</h2>
    <p>البناء الضوئي هي العملية التي يصنع فيها النبات غذاءه بنفسه. يحتاج النبات
    في هذه العملية إلى ضوء الشمس والماء وثاني أكسيد الكربون.</p>
    <p>ينتج عن عملية البناء الضوئي سكر الجلوكوز، وهو غذاء النبات، وينتج أيضا
    غاز الأكسجين الذي يحتاجه الإنسان والحيوان للتنفس.</p>
    <h2>دورة الماء</h2>
    <p>تتبخر المياه من البحار والأنهار بفعل حرارة الشمس. يتصاعد بخار الماء إلى
    الأعلى ثم يبرد ويتكاثف مكونا السحاب. عندما تثقل السحب يسقط المطر.</p>
    """,
]

CSS = """
@font-face { font-family: ar; src: url(NotoNaskhArabic-Regular.ttf); }
body { font-family: ar; font-size: 14px; direction: rtl; text-align: right; }
h2 { font-size: 20px; color: #113355; }
p { line-height: 1.6; }
"""


def build(output: Path) -> None:
    archive = pymupdf.Archive()
    archive.add(FONT, "NotoNaskhArabic-Regular.ttf")
    document = pymupdf.open()
    for html in PAGES:
        page = document.new_page()
        page.insert_htmlbox(
            pymupdf.Rect(40, 40, 555, 800),
            html,
            css=CSS,
            archive=archive,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(output)
    document.close()


if __name__ == "__main__":
    target = Path(__file__).resolve().parent.parent / "data" / "books" / "sample_science_grade4.pdf"
    build(target)
    print(f"wrote {target}")