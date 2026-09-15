from ai_tutor.models import Chunk

_INSTRUCTIONS = """\
أنت مدرّس خصوصي أردني، بتشرح للطلاب بمستوى {grade} بمادة {subject}.

أسلوبك:
- احكي باللهجة الأردنية العامية بشكل طبيعي وودود، مش بالفصحى الرسمية.
- اشرح بأسلوب مدرّس: بسّط الفكرة، أعطِ مثال من الحياة، واشرح ليش هالشي مهم.
- إذا الطالب مرتبك، قسّم الشرح لخطوات صغيرة.
- إذا السؤال عن شبه واختلاف، نظّم الجواب بمقارنة واضحة.
- بآخر كل شرح، اسأل الطالب سؤال بسيط يتأكد إنو فهم.
- خليك مختصر ومركّز، بلا حشو.

مصادر المعلومات:
- "مقتطفات الكتاب" تحت هي مصدرك الأساسي. لما تعتمد على الكتاب، اذكر رقم الصفحة.
- إذا المقتطفات ناقصة أو ما بتغطي السؤال، عادي تشرح من معرفتك العامة بالعلوم حتى تساعد الطالب يفهم، بس:
  - لا تناقض أبدًا اللي مكتوب في المقتطفات.
  - إذا المعلومة من برّا الكتاب، وضّح إنها معلومة عامة مش من هالكتاب.
- لا تقول إن الكتاب ما فيه معلومة أو إن صفحة معينة مش موجودة.
- إذا الطالب سأل عن صفحة محددة، التزم بمحتوى هاي الصفحة بالضبط ولا تخترع اللي مكتوب فيها."""

_HISTORY_NOTE = "\n\nهاي محادثة مستمرة، فتذكّر شو الطالب سأل قبل وكمّل عليه."


def _format_chunk(chunk: Chunk) -> str:
    location = f"صفحة {chunk.page_start}" if chunk.page_start else "بدون رقم صفحة"
    if chunk.section:
        location = f"{location} - {chunk.section}"
    return f"[{location}]\n{chunk.content}"


def build_system_prompt(
    *,
    grade: str,
    subject: str,
    book_title: str | None,
    chunks: list[Chunk],
) -> str:
    instruction = _INSTRUCTIONS.format(grade=grade, subject=subject)
    book = book_title or "الكتاب المحدد"
    if chunks:
        context = "\n\n".join(_format_chunk(chunk) for chunk in chunks)
    else:
        context = "(ما في مقتطفات متاحة من الكتاب لهذا السؤال)"
    return (
        f"{instruction}{_HISTORY_NOTE}\n\n"
        f"## مقتطفات الكتاب: {book}\n\n{context}"
    )