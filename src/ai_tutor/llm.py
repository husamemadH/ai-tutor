import json
from collections.abc import Iterator

from tenacity import retry, stop_after_attempt, wait_exponential

from ai_tutor.config import get_settings
from ai_tutor.openrouter import build_client


class ChatClient:
    """Chat completions via OpenRouter, with streaming."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = build_client()

    def _payload(
        self, messages: list[dict[str, str]], temperature: float, stream: bool
    ) -> dict:
        return {
            "model": self._settings.chat_model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
            "provider": {"sort": "latency", "allow_fallbacks": True},
        }

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(min=1, max=20), reraise=True)
    def complete(self, messages: list[dict[str, str]], temperature: float = 0.4) -> str:
        response = self._client.post(
            "/chat/completions", json=self._payload(messages, temperature, False)
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def stream(self, messages: list[dict[str, str]], temperature: float = 0.4) -> Iterator[str]:
        """Yield text deltas as they arrive (SSE)."""
        with self._client.stream(
            "POST", "/chat/completions", json=self._payload(messages, temperature, True)
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                delta = json.loads(data)["choices"][0].get("delta", {}).get("content")
                if delta:
                    yield delta