"""Configuration management for TaarYa."""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    
    # LLM Configuration
    openai_api_key: Optional[str] = None
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "kimi-k2.5:cloud"
    
    # Database - Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "taarya123"
    
    # Database - PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "astronomy"
    postgres_user: str = "taarya"
    postgres_password: str = "taarya123"
    
    # Database - Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    
    # Embedding Model
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    
    # Application
    log_level: str = "INFO"
    environment: str = "development"
    
    @property
    def postgres_url(self) -> str:
        """Construct PostgreSQL connection URL."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
    
    @property
    def use_openai(self) -> bool:
        """Check if OpenAI should be used."""
        return self.openai_api_key is not None


# Global settings instance
settings = Settings()
