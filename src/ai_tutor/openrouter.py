import httpx

from ai_tutor.config import get_settings


def build_client() -> httpx.Client:
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return httpx.Client(
        base_url=settings.openrouter_base_url,
        headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
        timeout=settings.request_timeout,
    )