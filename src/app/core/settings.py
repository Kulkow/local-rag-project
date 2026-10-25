from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: SecretStr
    redis_url: str = "redis://redis:6379/0"
    qdrant_url: str = "http://qdrant:6333"
    minio_url: str = "http://minio:9000"
    ollama_url: str = "http://host.docker.internal:11434"
    chat_model: str = "qwen3:4b"
    embedding_model: str = "embeddinggemma:latest"
    admin_username: str
    admin_password: SecretStr
