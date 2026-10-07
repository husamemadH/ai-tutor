from pathlib import Path

import httpx

from ai_tutor.config import get_settings
from ai_tutor.observability import observe_provider

MIN_AUDIO_BYTES = 400
MAX_AUDIO_BYTES = 1_500_000
_ALLOWED_SUFFIXES = {".webm", ".wav", ".mp3", ".mp4", ".ogg", ".m4a", ".mpeg", ".mpga", ".flac"}


class SttError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


def transcribe(audio: bytes, filename: str, content_type: str | None) -> str:
    settings = get_settings()
    if not settings.groq_api_key:
        raise SttError("GROQ_API_KEY is not set", 503)
    if len(audio) < MIN_AUDIO_BYTES:
        raise SttError("Audio too short", 400)
    if len(audio) > MAX_AUDIO_BYTES:
        raise SttError("Audio too long", 413)
    suffix = Path(filename or "clip.webm").suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        filename = "clip.webm"
        content_type = content_type or "audio/webm"

    with (
        observe_provider("groq", "stt", settings.stt_model) as observed,
        httpx.Client(
            base_url=settings.groq_base_url,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            timeout=settings.request_timeout,
        ) as client,
    ):
        response = client.post(
            "/audio/transcriptions",
            files={
                "file": (
                    filename,
                    audio,
                    content_type or "application/octet-stream",
                )
            },
            data={
                "model": settings.stt_model,
                "language": "ar",
                "temperature": "0",
            },
        )
        observed.status = response.status_code
        if response.status_code == 429:
            raise SttError("Speech service busy", 429)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SttError("Speech service failed", 502) from exc
        return (response.json().get("text") or "").strip()
