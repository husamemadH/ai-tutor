import base64
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf
from tenacity import retry, stop_after_attempt, wait_exponential

from ai_tutor.config import get_settings
from ai_tutor.ingest.parse import Page
from ai_tutor.openrouter import build_client

_OCR_INSTRUCTION = """\
أنت أداة تفريغ نصوص.
- الصورة الأولى هي الصفحة كاملة: فرّغ منها كل النص العربي والإنجليزي والمعادلات كما يظهر، \
مع الحفاظ على ترتيب الفقرات والأسطر.
- الصورتان الثانية والثالثة هما شريط أسفل الصفحة وشريط أعلاها: اقرأ منهما فقط رقم الصفحة المطبوع.
- تجاهل تمامًا أي أرقام داخل متن الصفحة (أرقام أسئلة أو تمارين أو أشكال).
قواعد الإخراج:
- السطر الأول لازم يكون رقم الصفحة، بهذا الشكل بالضبط: PAGE:<الرقم>
- إذا ما في رقم صفحة ظاهر في الشريطين، اكتب: PAGE:none
- بعد السطر الأول ضع النص المفرّغ فقط، بلا شرح أو تعليق، وبلا تكرار لرقم الصفحة."""

_PAGE_RE = re.compile(r"PAGE\s*[:=]\s*([0-9\u0660-\u0669]+|none)", re.IGNORECASE)
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def parse_ocr_output(content: str) -> tuple[int | None, str]:
    """Split the model output into (printed_page, text)."""
    lines = (content or "").splitlines()
    printed: int | None = None
    start = 0
    for index, line in enumerate(lines[:2]):
        match = _PAGE_RE.search(line)
        if match:
            value = match.group(1)
            if value.lower() != "none":
                printed = int(value.translate(_ARABIC_DIGITS))
            start = index + 1
            break
    return printed, "\n".join(lines[start:]).strip()


def _b64(pix: pymupdf.Pixmap) -> str:
    return base64.b64encode(pix.tobytes("png")).decode()


class OcrClient:
    """Transcribe PDF pages with a vision model (for scanned / lossy-encoded books)."""

    def __init__(self, model: str | None = None, workers: int = 6) -> None:
        self._settings = get_settings()
        self._model = model or self._settings.ocr_model
        self._workers = workers
        self._client = build_client()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=15), reraise=True)
    def _transcribe(self, full: str, bottom: str, top: str) -> str:
        response = self._client.post(
            "/chat/completions",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": _OCR_INSTRUCTION},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "فرّغ محتوى هذه الصفحة."},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{full}"}},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{bottom}"}},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{top}"}},
                        ],
                    },
                ],
                "temperature": 0,
                "max_tokens": 4096,
                "provider": {"sort": "latency", "allow_fallbacks": True},
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"] or ""

    def ocr_pdf(self, path: Path) -> list[Page]:
        """Render every page, transcribe concurrently, return pages in order."""
        renders: list[tuple[int, str, str, str]] = []
        with pymupdf.open(path) as doc:
            for index, page in enumerate(doc, start=1):
                rect = page.rect
                strip_height = rect.height * 0.09
                full = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
                bottom = page.get_pixmap(
                    matrix=pymupdf.Matrix(4, 4),
                    clip=pymupdf.Rect(rect.x0, rect.y1 - strip_height, rect.x1, rect.y1),
                )
                top = page.get_pixmap(
                    matrix=pymupdf.Matrix(4, 4),
                    clip=pymupdf.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + strip_height),
                )
                renders.append((index, _b64(full), _b64(bottom), _b64(top)))

        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            outputs = list(
                pool.map(lambda r: self._transcribe(r[1], r[2], r[3]), renders)
            )

        total = len(renders)
        pages: list[Page] = []
        for (number, *_), output in zip(renders, outputs, strict=True):
            printed, text = parse_ocr_output(output)
            if printed is not None and not 1 <= printed <= total:
                printed = None
            pages.append(Page(number=number, text=text, printed_number=printed))
        return pages