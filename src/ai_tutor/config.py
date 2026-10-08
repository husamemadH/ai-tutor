from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    stt_model: str = "whisper-large-v3-turbo"
    stt_max_seconds: int = 30

    azure_speech_key: str = ""
    azure_speech_region: str = ""
    azure_tts_voice: str = "ar-SA-HamedNeural"
    azure_tts_rate: str = "0%"
    azure_tts_format: str = "audio-24khz-48kbitrate-mono-mp3"
    azure_tts_max_chars: int = 2000

    tutor_dialect: str = "jordanian"

    chat_model: str = "deepseek/deepseek-v4.1-flash"
    ocr_model: str = "google/gemini-2.5-flash"
    embedding_model: str = "baai/bge-m3"
    embedding_dim: int = 1024

    database_url: str = "postgresql+psycopg://ai_tutor:ai_tutor@localhost:5433/ai_tutor"

    retrieval_top_k: int = 6
    memory_window_turns: int = 8
    request_timeout: float = 120.0
    tutor_service_token: str = ""
    tutor_max_concurrent: int = 4
    tutor_generation_timeout: float = 120.0

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, value: str) -> str:
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix):]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
