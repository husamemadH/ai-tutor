import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf
from tenacity import retry, stop_after_attempt, wait_exponential

from ai_tutor.config import get_settings
from ai_tutor.ingest.parse import Page
from ai_tutor.openrouter import build_client

_OCR_INSTRUCTION = (
    "أنت أداة تفريغ نصوص. فرّغ كل النص العربي والإنجليزي والمعادلات في الصفحة كما يظهر، "
    "مع الحفاظ على ترتيب الفقرات والأسطر. لا تضف أي شرح أو تعليق، وأخرج النص المفرّغ فقط."
)


class OcrClient:
    """Transcribe PDF pages with a vision model (for scanned / lossy-encoded books)."""

    def __init__(self, model: str | None = None, workers: int = 6) -> None:
        self._settings = get_settings()
        self._model = model or self._settings.chat_model
        self._workers = workers
        self._client = build_client()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=15), reraise=True)
    def _transcribe(self, png_b64: str) -> str:
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
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{png_b64}"},
                            },
                        ],
                    },
                ],
                "temperature": 0,
                "provider": {"sort": "latency", "allow_fallbacks": True},
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"] or ""

    def ocr_pdf(self, path: Path) -> list[Page]:
        """Render every page, transcribe concurrently, return pages in order."""
        renders: list[tuple[int, str]] = []
        with pymupdf.open(path) as doc:
            for index, page in enumerate(doc, start=1):
                pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
                renders.append((index, base64.b64encode(pix.tobytes("png")).decode()))

        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            results = list(pool.map(lambda item: self._transcribe(item[1]), renders))

        return [
            Page(number=number, text=text)
            for (number, _), text in zip(renders, results, strict=True)
        ]