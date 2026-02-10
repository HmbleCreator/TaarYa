"""Initialize PostgreSQL database with Q3C extension and tables."""
import logging
from sqlalchemy import text
from src.database import postgres_conn
from src.models import Base

logger = logging.getLogger(__name__)


def init_database():
    """Initialize database: create Q3C extension and all tables."""
    
    postgres_conn.connect()
    
    try:
        # Create Q3C extension if not exists
        with postgres_conn.session() as session:
            logger.info("Creating Q3C extension...")
            session.execute(text("CREATE EXTENSION IF NOT EXISTS q3c;"))
            session.commit()
            logger.info("Q3C extension ready")
        
        # Create all tables
        logger.info("Creating database tables...")
        Base.metadata.create_all(bind=postgres_conn.engine)
        logger.info("Database initialized successfully")
        
        # Verify Q3C is working
        with postgres_conn.session() as session:
            result = session.execute(text("SELECT q3c_version();"))
            version = result.scalar()
            logger.info(f"Q3C version: {version}")
        
        return True
        
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise


if __name__ == "__main__":
    from src.utils.logger import setup_logging
    setup_logging()
    init_database()
