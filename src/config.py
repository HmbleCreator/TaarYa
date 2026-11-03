"""Configuration management for TaarYa without pydantic runtime dependency."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency
    load_dotenv = None


if load_dotenv is not None:
    load_dotenv(".env", override=False)


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _get_env_int(name: str, default: int) -> int:
    value = _get_env(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_env_bool(name: str, default: bool) -> bool:
    value = _get_env(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass(slots=True)
class Settings:
    """Application settings loaded from environment variables."""

    openai_api_key: Optional[str] = _get_env("OPENAI_API_KEY")
    ollama_base_url: str = _get_env("OLLAMA_BASE_URL", "http://localhost:11434") or "http://localhost:11434"
    ollama_model: str = _get_env("OLLAMA_MODEL", "glm-4.6:cloud") or "glm-4.6:cloud"

    neo4j_uri: str = _get_env("NEO4J_URI", "bolt://localhost:7687") or "bolt://localhost:7687"
    neo4j_user: str = _get_env("NEO4J_USER", "neo4j") or "neo4j"
    neo4j_password: str = _get_env("NEO4J_PASSWORD", "taarya123") or "taarya123"

    database_url: Optional[str] = _get_env("DATABASE_URL")
    postgres_host: str = _get_env("POSTGRES_HOST", "localhost") or "localhost"
    postgres_port: int = _get_env_int("POSTGRES_PORT", 5432)
    postgres_db: str = _get_env("POSTGRES_DB", "astronomy") or "astronomy"
    postgres_user: str = _get_env("POSTGRES_USER", "taarya") or "taarya"
    postgres_password: str = _get_env("POSTGRES_PASSWORD", "taarya123") or "taarya123"

    qdrant_host: str = _get_env("QDRANT_HOST", "localhost") or "localhost"
    qdrant_port: int = _get_env_int("QDRANT_PORT", 6333)
    graph_auto_sync: bool = _get_env_bool("GRAPH_AUTO_SYNC", True)
    graph_link_simbad_enabled: bool = _get_env_bool("GRAPH_LINK_SIMBAD_ENABLED", False)
    graph_link_name_fallback_enabled: bool = _get_env_bool(
        "GRAPH_LINK_NAME_FALLBACK_ENABLED", False
    )
    graph_link_max_identifiers_per_paper: int = _get_env_int(
        "GRAPH_LINK_MAX_IDENTIFIERS_PER_PAPER", 12
    )
    graph_link_max_simbad_queries: int = _get_env_int("GRAPH_LINK_MAX_SIMBAD_QUERIES", 25)

    embedding_model: str = (
        _get_env("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        or "sentence-transformers/all-MiniLM-L6-v2"
    )

    log_level: str = _get_env("LOG_LEVEL", "INFO") or "INFO"
    environment: str = _get_env("ENVIRONMENT", "development") or "development"

    @property
    def postgres_url(self) -> str:
        """Construct PostgreSQL connection URL."""
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def use_openai(self) -> bool:
        """Check if OpenAI should be used."""
        return bool(self.openai_api_key)


settings = Settings()
