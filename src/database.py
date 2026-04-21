"""Database connection managers."""
from typing import Any, Optional, TYPE_CHECKING
from contextlib import contextmanager
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config import settings

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from qdrant_client import QdrantClient


class Neo4jConnection:
    """Neo4j graph database connection manager."""

    # Background-retry settings (used after startup, non-blocking)
    _BG_RETRY_DELAY  = 20  # seconds between background attempts

    def __init__(self):
        self.driver: Optional[Any] = None

    # ------------------------------------------------------------------
    # connect() — single attempt, raises immediately if unreachable.
    # Called at startup (once) and by the background retry task.
    # ------------------------------------------------------------------
    def connect(self):
        """Try once to connect and verify Neo4j's Bolt port.

        Raises on failure so the caller can decide whether to retry.
        The driver constructor is lazy and never opens a socket on its own;
        verify_connectivity() is what actually tests the connection.
        """
        if self.driver is not None:
            return  # already connected

        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        driver.verify_connectivity()   # raises if Bolt port not reachable
        self.driver = driver
        logger.info("Connected to Neo4j")

    # ------------------------------------------------------------------
    # connect_with_retry() — async, meant to run as a background task
    # via asyncio.create_task().  Does NOT block the ASGI event loop.
    # ------------------------------------------------------------------
    async def connect_with_retry(self):
        """Background coroutine: keep retrying until Neo4j is reachable.

        Loops indefinitely — never gives up. Neo4j can take several
        minutes to fully boot on a resource-constrained machine.
        Uses asyncio.sleep so the ASGI event loop is never blocked.
        """
        import asyncio

        attempt = 0
        while True:
            await asyncio.sleep(self._BG_RETRY_DELAY)
            if self.driver is not None:
                return  # already connected (e.g. reconnected elsewhere)
            attempt += 1
            try:
                self.connect()
                logger.info(f"Neo4j: background connection established ✓ (attempt {attempt})")
                return
            except Exception as exc:
                logger.warning(f"Neo4j background retry #{attempt}: {exc}")

    def close(self):
        """Close Neo4j connection."""
        if self.driver:
            self.driver.close()
            self.driver = None
            logger.info("Neo4j connection closed")

    @contextmanager
    def session(self):
        """Context manager for Neo4j session.

        Raises RuntimeError with a clear message if Neo4j hasn't connected
        yet — the API layer's except blocks already surface this as a
        graceful 'neo4j: error' stat rather than crashing.
        """
        if self.driver is None:
            raise RuntimeError(
                "Neo4j driver not initialised — container may still be starting. "
                "Graph features are temporarily unavailable."
            )
        with self.driver.session() as session:
            yield session


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
        self.client: Optional["QdrantClient"] = None
    
    def connect(self):
        """Establish connection to Qdrant."""
        if self.client is None:
            from qdrant_client import QdrantClient

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
    
    def get_client(self) -> "QdrantClient":
        """Get Qdrant client instance."""
        self.connect()
        return self.client


# Global connection instances
neo4j_conn = Neo4jConnection()
postgres_conn = PostgresConnection()
qdrant_conn = QdrantConnection()
