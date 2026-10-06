import re
from xml.sax.saxutils import escape

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ai_tutor.config import get_settings

_CITATION = re.compile(r"[\[(][^\])]*صفح[^\])]*[\])]")
_MARKDOWN = re.compile(r"[*_`#]+")
_EMOTICON = re.compile(r"[:;=]-?[)(DPp/\\|]|<3|\^\^")
_EMOJI = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff"
    "\u2190-\u21ff\u2b00-\u2bff\ufe0f\u200d]+"
)
_SPACES = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_RATE = re.compile(r"^(?:[+-]?\d{1,3}%|x-slow|slow|medium|fast|x-fast)$")
_SENTENCE_END = re.compile(r"(?<=[.!?؟\n])")

_DIAC = "\u064b-\u0652\u0670"
_AR_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")

_MATH_WORDS = (
    ("≠", " لا يساوي "),
    ("≈", " يساوي تقريبا "),
    ("≤", " أصغر من أو يساوي "),
    ("≥", " أكبر من أو يساوي "),
    ("±", " زائد أو ناقص "),
    ("∴", " إذن "),
    ("∵", " لأن "),
    ("△", " مثلث "),
    ("π", " بَايْ "),
    ("×", " في "),
    ("*", " في "),
    ("÷", " على "),
    ("/", " على "),
    ("%", " بالمئة "),
    ("=", " يساوي "),
    ("+", " زائد "),
    ("^", " أس "),
)

_AR_LETTER_NAMES = {
    "أ": "ألف",
    "ب": "باء",
    "ج": "جيم",
    "د": "دال",
    "س": "سين",
    "ص": "صاد",
    "ع": "عين",
    "ل": "لام",
    "م": "ميم",
    "ن": "نون",
    "ق": "قاف",
    "ك": "كاف",
    "ر": "راء",
    "ط": "طاء",
    "ف": "فاء",
}

_ABBREVIATIONS = (
    (re.compile(r"(?<![\u0621-\u064a])نق(?![\u0621-\u064a])"), "نصف القطر"),
    (re.compile(r"(?<![\u0621-\u064a])سم(?![\u0621-\u064a])"), "سنتيمتر"),
)


def normalize_math(text: str) -> str:
    """Turn math symbols and single-letter variables into spoken Arabic for TTS."""
    text = text.replace("\u2212", "-").replace("–", "-").replace("—", "-")
    text = re.sub(r"([0-9\u0660-\u0669]+)\s*√", r"جذر \1", text)
    text = text.replace("√", " جذر ")

    def _exponent(match: re.Match) -> str:
        word = "مربع" if match.group(2) == "2" else "مكعب"
        return f"{match.group(1)} {word}"

    text = re.sub(r"(سم|نق|س|ص|ع|م|أ|ب|ج|د)([23])", _exponent, text)
    text = re.sub(r"(\d)[,٫](\d)", r"\1 فاصلة \2", text)
    text = re.sub(
        r"([\u0621-\u064a0-9\u0660-\u0669)\]])\s*-\s*(?=[0-9\u0660-\u0669(])",
        r"\1 ناقص ",
        text,
    )
    text = re.sub(r"-\s*(?=[0-9\u0660-\u0669(])", " سالب ", text)
    text = re.sub(r"\s-\s", " ناقص ", text)
    for symbol, word in _MATH_WORDS:
        text = text.replace(symbol, word)
    text = text.translate(_AR_DIGITS)

    for pattern, word in _ABBREVIATIONS:
        text = pattern.sub(word, text)

    def _letter(match: re.Match) -> str:
        return _AR_LETTER_NAMES[match.group(1)]

    text = re.sub(
        rf"(?<![\u0621-\u064a])([أبجدسصعملنقكرفط])[{_DIAC}]*+(?![\u0621-\u064a])",
        _letter,
        text,
    )
    return _SPACES.sub(" ", text).strip()


def sanitize(text: str) -> str:
    """Strip citations, markdown, emoticons/emoji, then expand math into spoken Arabic."""
    text = _CITATION.sub("", text or "")
    text = _MARKDOWN.sub("", text)
    text = _EMOTICON.sub(" ", text)
    text = _EMOJI.sub(" ", text)
    text = _SPACES.sub(" ", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return normalize_math(text.strip())


class TtsError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


def _build_ssml(text: str, voice: str, rate: str) -> str:
    lang = "-".join(voice.split("-")[:2])
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{lang}">'
        f'<voice name="{escape(voice)}">'
        f'<prosody rate="{rate}">{escape(text)}</prosody>'
        "</voice>"
        "</speak>"
    )


def split_for_tts(text: str, max_chars: int) -> list[str]:
    """Split into <= max_chars pieces at sentence boundaries, word-wrapping overflow."""
    chunks: list[str] = []
    buf = ""

    def push() -> None:
        nonlocal buf
        if buf.strip():
            chunks.append(buf.strip())
        buf = ""

    for sentence in _SENTENCE_END.split(text):
        if buf and len(buf) + len(sentence) > max_chars:
            push()
        if len(sentence) <= max_chars:
            buf += sentence
            continue
        word = ""
        for token in sentence.split():
            if len(token) > max_chars:
                if word:
                    chunks.append(word)
                    word = ""
                chunks.extend(
                    token[i : i + max_chars] for i in range(0, len(token), max_chars)
                )
                continue
            if word and len(word) + len(token) + 1 > max_chars:
                chunks.append(word)
                word = ""
            word = f"{word} {token}".strip()
        buf = word
    push()
    return chunks


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
def _synth_chunk(clean: str, voice: str, speed: str) -> bytes:
    settings = get_settings()
    url = (
        f"https://{settings.azure_speech_region}.tts.speech.microsoft.com"
        "/cognitiveservices/v1"
    )
    response = httpx.post(
        url,
        headers={
            "Ocp-Apim-Subscription-Key": settings.azure_speech_key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": settings.azure_tts_format,
            "User-Agent": "ai-tutor",
        },
        content=_build_ssml(clean, voice, speed).encode("utf-8"),
        timeout=settings.request_timeout,
    )
    if response.status_code == 429:
        raise TtsError("Speech service busy", 429)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise TtsError("Speech service failed", 502) from exc
    return response.content


def synthesize(text: str, voice: str | None = None, rate: str | None = None) -> bytes:
    """Synthesize arbitrary-length text, concatenating Azure's per-request MP3 chunks."""
    settings = get_settings()
    if not settings.azure_speech_key or not settings.azure_speech_region:
        raise TtsError("Azure speech is not configured", 503)
    clean = sanitize(text)
    if not clean:
        raise TtsError("Empty text", 400)
    speed = rate or settings.azure_tts_rate
    if not _RATE.match(speed):
        raise TtsError("Invalid speech rate", 400)
    chosen = voice or settings.azure_tts_voice
    chunks = split_for_tts(clean, settings.azure_tts_max_chars)
    return b"".join(_synth_chunk(chunk, chosen, speed) for chunk in chunks)
