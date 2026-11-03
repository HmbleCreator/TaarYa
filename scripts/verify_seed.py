"""Quick verification of seeded clusters."""
import sys
sys.path.insert(0, '.')
from src.database import postgres_conn
from sqlalchemy import text

postgres_conn.connect()
with postgres_conn.session() as session:
    # Check regions
    result = session.execute(text(
        "SELECT name, star_count FROM regions WHERE name IN "
        "('Coma Berenices', 'Praesepe', 'NGC 2516', 'Alpha Persei', 'IC 2391')"
    ))
    print("Regions:")
    for row in result:
        print(f"  {row[0]}: {row[1]} stars")

    # Total stars
    result = session.execute(text("SELECT COUNT(*) FROM stars"))
    print(f"\nTotal stars in DB: {result.scalar()}")

    # bp_rp check
    result = session.execute(text("SELECT COUNT(*) FROM stars WHERE bp_rp IS NOT NULL"))
    print(f"Stars with bp_rp set: {result.scalar()}")

    # Synthetic stars
    result = session.execute(text("SELECT COUNT(*) FROM stars WHERE catalog_source = 'SYNTHETIC_BENCHMARK'"))
    print(f"Synthetic benchmark stars: {result.scalar()}")

    # Sample
    result = session.execute(text(
        "SELECT source_id, phot_g_mean_mag, bp_rp FROM stars "
        "WHERE catalog_source = 'SYNTHETIC_BENCHMARK' LIMIT 3"
    ))
    print("\nSample synthetic stars:")
    for row in result:
        print(f"  {row[0]}: G={row[1]:.2f}, bp_rp={row[2]:.2f}")
