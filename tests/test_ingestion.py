"""Test script to verify ingestion pipeline."""
import logging
import sys

from src.utils.logger import setup_logging
from src.init_db import init_database
from src.ingestion.gaia_parser import GaiaParser

logger = logging.getLogger(__name__)


def test_database_connection():
    """Test PostgreSQL connection."""
    logger.info("Testing database connection...")
    
    try:
        from src.database import postgres_conn
        postgres_conn.connect()
        
        with postgres_conn.session() as session:
            from sqlalchemy import text
            result = session.execute(text("SELECT version();"))
            version = result.scalar()
            logger.info(f"PostgreSQL version: {version}")
        
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        assert False, f"Database connection failed: {e}"

    assert True


def test_q3c_extension():
    """Test Q3C extension."""
    logger.info("Testing Q3C extension...")
    
    try:
        from src.database import postgres_conn
        
        with postgres_conn.session() as session:
            from sqlalchemy import text
            
            # Test Q3C version
            result = session.execute(text("SELECT q3c_version();"))
            version = result.scalar()
            logger.info(f"Q3C version: {version}")
            
            # Match the application's five-argument predicate shape and cast
            # literals explicitly so PostgreSQL resolves the extension function.
            result = session.execute(text("""
                SELECT q3c_radial_query(
                    83.8221::double precision,
                    -5.3911::double precision,
                    83.8221::double precision,
                    -5.3911::double precision,
                    1.0::double precision
                );
            """))
            assert result.scalar() is True
            logger.info("Q3C cone search function works!")
        
    except Exception as e:
        logger.error(f"Q3C test failed: {e}")
        logger.info("Q3C extension may not be installed. Run: python -m src.init_db")
        assert False, f"Q3C test failed: {e}"

    assert True


def test_gaia_parser(tmp_path):
    """Test Gaia parser with sample data."""
    logger.info("Testing Gaia parser...")
    
    # Create sample CSV data
    sample_csv = tmp_path / "test_sample.csv"
    sample_data = """source_id,ra,dec,parallax,pmra,pmdec,phot_g_mean_mag
1234567890,83.8221,-5.3911,1.23,5.1,-2.3,12.5
9876543210,84.0512,-5.2145,0.98,3.2,-1.8,13.2
"""
    
    sample_csv.write_text(sample_data)
    
    try:
        parser = GaiaParser(chunk_size=10)
        count = 0
        
        for chunk in parser.parse_csv(sample_csv):
            logger.info(f"Parsed chunk with {len(chunk)} rows")
            logger.debug(f"Columns: {chunk.columns.tolist()}")
            count += len(chunk)
        
        logger.info(f"Total parsed: {count} records")
        
    except Exception as e:
        logger.error(f"Parser test failed: {e}")
        assert False, f"Parser test failed: {e}"

    assert count == 2


def main():
    """Run all tests."""
    setup_logging()
    
    logger.info("="*60)
    logger.info("TaarYa Ingestion Pipeline Tests")
    logger.info("="*60)
    
    tests = [
        ("Database Connection", test_database_connection),
        ("Q3C Extension", test_q3c_extension),
        ("Gaia Parser", test_gaia_parser),
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        logger.info(f"\n--- Running: {test_name} ---")
        try:
            results[test_name] = test_func()
        except Exception as e:
            logger.error(f"Test crashed: {e}")
            results[test_name] = False
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("Test Summary:")
    logger.info("="*60)
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"{test_name}: {status}")
    
    all_passed = all(results.values())
    logger.info("="*60)
    
    if all_passed:
        logger.info("🎉 All tests passed!")
        logger.info("\nNext steps:")
        logger.info("1. Download Gaia DR3 sample data")
        logger.info("2. Run: python -m src.ingestion.gaia_ingestor <filepath>")
        return 0
    else:
        logger.error("❌ Some tests failed. Check the logs above.")
        logger.info("\nMake sure:")
        logger.info("1. Docker containers are running: docker-compose up -d")
        logger.info("2. Database is initialized: python -m src.init_db")
        return 1


if __name__ == "__main__":
    sys.exit(main())
