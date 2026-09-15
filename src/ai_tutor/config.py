from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    chat_model: str = "deepseek/deepseek-v4.1-flash"
    embedding_model: str = "baai/bge-m3"
    embedding_dim: int = 1024

    database_url: str = "postgresql+psycopg://ai_tutor:ai_tutor@localhost:5433/ai_tutor"

    retrieval_top_k: int = 6
    memory_window_turns: int = 8
    request_timeout: float = 120.0


@lru_cache
def get_settings() -> Settings:
    return Settings()