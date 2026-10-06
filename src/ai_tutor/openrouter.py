import time
from contextvars import ContextVar

import httpx

from ai_tutor.config import get_settings

generation_deadline: ContextVar[float | None] = ContextVar("generation_deadline", default=None)


def constrain_request(request: httpx.Request) -> None:
    deadline = generation_deadline.get()
    if deadline is None:
        return
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Generation deadline exceeded")
    request.extensions["timeout"] = httpx.Timeout(min(30.0, remaining)).as_dict()


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
        event_hooks={"request": [constrain_request]},
    )
