from tenacity import retry, stop_after_attempt, wait_exponential

from ai_tutor.config import get_settings
from ai_tutor.openrouter import build_client


class EmbeddingClient:
    """Batched embeddings via OpenRouter (/embeddings)."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = build_client()

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(min=1, max=20), reraise=True)
    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client.post(
            "/embeddings",
            json={
                "model": self._settings.embedding_model,
                "input": texts,
                "provider": {"sort": "latency", "allow_fallbacks": True},
            },
        )
        response.raise_for_status()
        data = response.json()["data"]
        return [item["embedding"] for item in data]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]