import re
from xml.sax.saxutils import escape

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ai_tutor.config import get_settings
from ai_tutor.observability import observe_provider

_CITATION = re.compile(r"[\[(][^\])]*صفح[^\])]*[\])]")
_MARKDOWN = re.compile(r"\*\*|__|`+|(?m:^[ \t]*#{1,6}[ \t]+)")
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


def latex_to_speech(text: str) -> str:
    commands = {
        "Delta": "دلتا",
        "delta": "دلتا",
        "pi": "π",
        "theta": "ثيتا",
        "alpha": "ألفا",
        "beta": "بيتا",
        "pm": "±",
        "times": "×",
        "cdot": "×",
        "div": "÷",
        "approx": "≈",
        "neq": "≠",
        "le": "≤",
        "leq": "≤",
        "ge": "≥",
        "geq": "≥",
        "infty": "ما لا نهاية",
        "sin": "جيب",
        "cos": "جيب تمام",
        "tan": "ظل",
        "log": "لوغاريتم",
        "ln": "لوغاريتم طبيعي",
        "sum": "مجموع",
        "int": "تكامل",
        "left": "",
        "right": "",
        "displaystyle": "",
        "quad": " ",
        "qquad": " ",
    }
    letters = {
        "a": "إيه",
        "b": "بي",
        "c": "سي",
        "d": "دي",
        "e": "إي",
        "f": "إف",
        "g": "جي",
        "h": "إتش",
        "i": "آي",
        "j": "جاي",
        "k": "كي",
        "l": "إل",
        "m": "إم",
        "n": "إن",
        "o": "أو",
        "p": "بي",
        "q": "كيو",
        "r": "آر",
        "s": "إس",
        "t": "تي",
        "u": "يو",
        "v": "في",
        "w": "دبليو",
        "x": "إكس",
        "y": "واي",
        "z": "زد",
    }
    text = re.sub(r"(^|[={\[(+])\s*-\s*", r"\1 سالب ", text).replace("-", " ناقص ")
    position = 0

    def argument(depth: int) -> str:
        nonlocal position
        while position < len(text) and text[position].isspace():
            position += 1
        if position >= len(text):
            return ""
        if text[position] == "{":
            position += 1
            return read("}", depth + 1)
        return atom(depth + 1)

    def atom(depth: int) -> str:
        nonlocal position
        char = text[position]
        position += 1
        if char == "\\":
            match = re.match(r"[a-zA-Z]+", text[position:])
            if not match:
                if position < len(text):
                    position += 1
                return " "
            command = match.group()
            position += len(command)
            if command in {"frac", "dfrac", "tfrac"}:
                numerator = argument(depth)
                denominator = argument(depth)
                return f" الكسر {numerator} على {denominator} نهاية الكسر "
            if command == "sqrt":
                while position < len(text) and text[position].isspace():
                    position += 1
                index = ""
                if position < len(text) and text[position] == "[":
                    position += 1
                    index = read("]", depth + 1)
                value = argument(depth)
                root = f"الجذر من الدرجة {index}" if index else "الجذر التربيعي"
                return f" {root} لـ {value} نهاية الجذر "
            if command in {"text", "mathrm", "operatorname", "mathbf", "mathit"}:
                return argument(depth)
            if command not in commands:
                raise TtsError("Unsupported math notation for speech", 422)
            return f" {commands[command]} "
        if char == "{":
            return read("}", depth + 1)
        if char in "^_":
            value = argument(depth).strip()
            if char == "_":
                return f" رقم {value} "
            return f" { {'2': 'تربيع', '3': 'تكعيب'}.get(value, f'أس {value}') } "
        if char.isascii() and char.isalpha():
            previous = text[position - 2] if position > 1 else ""
            product = "في " if previous and previous.isascii() and previous.isalnum() else ""
            return f" {product}{letters.get(char.lower(), char)} "
        return char

    def read(end: str = "", depth: int = 0) -> str:
        nonlocal position
        if depth > 40:
            raise TtsError("Math expression is too deeply nested", 400)
        parts = []
        while position < len(text):
            if end and text[position] == end:
                position += 1
                break
            parts.append(atom(depth))
        return "".join(parts)

    return read()


def normalize_math(text: str) -> str:
    """Turn math symbols and single-letter variables into spoken Arabic for TTS."""
    text = text.replace("\u2212", "-").replace("–", "-").replace("—", "-")
    text = re.sub(r"([0-9\u0660-\u0669]+)\s*√", r"جذر \1", text)
    text = text.replace("√", " جذر ")

    def _exponent(match: re.Match) -> str:
        word = "مربع" if match.group(2) == "2" else "مكعب"
        return f"{match.group(1)} {word}"

    text = re.sub(r"(سم|نق|س|ص|ع|م|أ|ب|ج|د)([23])", _exponent, text)
    decimal_digits = dict(
        zip(
            "0123456789",
            ["صفر", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة"],
        )
    )

    def _decimal(match: re.Match) -> str:
        fraction = " ".join(decimal_digits[str(int(digit))] for digit in match.group(2))
        return f"{match.group(1)} فاصلة {fraction}"

    text = re.sub(r"(\d+)[,.٫](\d+)", _decimal, text)
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
        rf"(?<![\u0621-\u064a{_DIAC}])([أبجدسصعملنقكرفط])[{_DIAC}]*+(?![\u0621-\u064a])",
        _letter,
        text,
    )
    return re.sub(r"(?m)^[ \t]+|[ \t]+$", "", _SPACES.sub(" ", text)).strip()


def sanitize(text: str) -> str:
    """Strip citations, markdown, emoticons/emoji, then expand math into spoken Arabic."""
    text = _CITATION.sub("", text or "")
    text = re.sub(r"(?m)^[ \t]*(?:[-*_][ \t]*){3,}$", "", text)
    text = re.sub(r"(?m)^[ \t]*[-*+][ \t]+(?=\S)", "", text)
    text = re.sub(
        r"\$\$([\s\S]*?)\$\$|\$([^$\n]+)\$|\\\[([\s\S]*?)\\\]|\\\(([\s\S]*?)\\\)",
        lambda match: latex_to_speech(next(group for group in match.groups() if group is not None)),
        text,
    )
    text = _MARKDOWN.sub("", text)
    text = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", text)
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
                chunks.extend(token[i : i + max_chars] for i in range(0, len(token), max_chars))
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
    url = f"https://{settings.azure_speech_region}.tts.speech.microsoft.com/cognitiveservices/v1"
    with observe_provider("azure", "tts", voice) as observed:
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
        observed.status = response.status_code
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
