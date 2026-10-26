from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)
    database_url: SecretStr
    redis_url: str = "redis://redis:6379/0"
    qdrant_url: str = "http://qdrant:6333"
    minio_url: str = "http://minio:9000"
    ollama_url: str = "http://host.docker.internal:11434"
    chat_model: str = "qwen3:4b"
    embedding_model: str = Field(default="embeddinggemma:latest", min_length=1, max_length=200)
    admin_username: str
    jwt_secret: SecretStr = Field(min_length=32)
    admin_password: SecretStr
    minio_access_key: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("MINIO_ACCESS_KEY", "MINIO_ROOT_USER")
    )
    minio_secret_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("MINIO_SECRET_KEY", "MINIO_ROOT_PASSWORD"),
    )
    documents_bucket: str = "rag-documents"

    rag_min_vector_score: float = Field(default=0.35, ge=-1, le=1)
    embedding_dimensions: int = Field(default=768, ge=1, le=8192)
    chunk_size: int = Field(default=1000, ge=1, le=8000)
    chunk_overlap: int = Field(default=150, ge=0)
    embedding_batch_size: int = Field(default=8, ge=1, le=32)
    max_document_chunks: int = Field(default=2000, ge=1, le=10000)

    @model_validator(mode="after")
    def validate_chunking(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be less than CHUNK_SIZE")
        return self
