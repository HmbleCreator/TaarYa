"""Database connection managers."""
from typing import Optional
from contextlib import contextmanager
import logging

from neo4j import GraphDatabase
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from qdrant_client import QdrantClient

from src.config import settings

logger = logging.getLogger(__name__)


class Neo4jConnection:
    """Neo4j graph database connection manager."""
    
    def __init__(self):
        self.driver = None
    
    def connect(self):
        """Establish connection to Neo4j."""
        if self.driver is None:
            self.driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password)
            )
            logger.info("Connected to Neo4j")
    
    def close(self):
        """Close Neo4j connection."""
        if self.driver:
            self.driver.close()
            self.driver = None
            logger.info("Neo4j connection closed")
    
    @contextmanager
    def session(self):
        """Context manager for Neo4j session."""
        self.connect()
        session = self.driver.session()
        try:
            yield session
        finally:
            session.close()


class PostgresConnection:
    """PostgreSQL database connection manager."""
    
    def __init__(self):
        self.engine = None
        self.SessionLocal = None
    
    def connect(self):
        """Establish connection to PostgreSQL."""
        if self.engine is None:
            self.engine = create_engine(settings.postgres_url)
            self.SessionLocal = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.engine
            )
            logger.info("Connected to PostgreSQL")
    
    def close(self):
        """Close PostgreSQL connection."""
        if self.engine:
            self.engine.dispose()
            self.engine = None
            logger.info("PostgreSQL connection closed")
    
    @contextmanager
    def session(self):
        """Context manager for database session."""
        self.connect()
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()


class QdrantConnection:
    """Qdrant vector database connection manager."""
    
    def __init__(self):
        self.client: Optional[QdrantClient] = None
    
    def connect(self):
        """Establish connection to Qdrant."""
        if self.client is None:
            self.client = QdrantClient(
                host=settings.qdrant_host,
                port=settings.qdrant_port
            )
            logger.info("Connected to Qdrant")
    
    def close(self):
        """Close Qdrant connection."""
        if self.client:
            self.client.close()
            self.client = None
            logger.info("Qdrant connection closed")
    
    def get_client(self) -> QdrantClient:
        """Get Qdrant client instance."""
        self.connect()
        return self.client


# Global connection instances
neo4j_conn = Neo4jConnection()
postgres_conn = PostgresConnection()
qdrant_conn = QdrantConnection()
