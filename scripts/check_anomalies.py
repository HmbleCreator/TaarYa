"""Check if synthetic stars have anomalous values."""
import sys
sys.path.insert(0, '.')

from src.database import postgres_conn
from sqlalchemy import text

postgres_conn.connect()
with postgres_conn.session() as session:
    print("=== Synthetic Cluster Stars Anomaly Check ===\n")
    
    # Check RUWE anomalies
    result = session.execute(text(
        "SELECT COUNT(*) FROM stars "
        "WHERE catalog_source = 'SYNTHETIC_BENCHMARK' AND ruwe > 1.4"
    ))
    print(f"Stars with RUWE > 1.4: {result.scalar()}")
    
    result = session.execute(text(
        "SELECT COUNT(*) FROM stars "
        "WHERE catalog_source = 'SYNTHETIC_BENCHMARK' AND ruwe > 2.0"
    ))
    print(f"Stars with RUWE > 2.0: {result.scalar()}")
    
    # Check BP-RP extremes
    result = session.execute(text(
        "SELECT COUNT(*) FROM stars "
        "WHERE catalog_source = 'SYNTHETIC_BENCHMARK' AND bp_rp < -0.1"
    ))
    print(f"Stars with BP-RP < -0.1 (blue outliers): {result.scalar()}")
    
    result = session.execute(text(
        "SELECT COUNT(*) FROM stars "
        "WHERE catalog_source = 'SYNTHETIC_BENCHMARK' AND bp_rp > 2.8"
    ))
    print(f"Stars with BP-RP > 2.8 (red outliers): {result.scalar()}")
    
    # Check proper motion extremes (relative to cluster means)
    # For clusters with high PM mean, check if any stars exceed 40 or 80 mas/yr
    result = session.execute(text(
        "SELECT name, pmra, pmdec FROM regions "
        "WHERE name IN ('Coma Berenices', 'Praesepe', 'NGC 2516', "
        "'Alpha Persei', 'IC 2391')"
    ))
    clusters = {row[0]: (row[1], row[2]) for row in result}
    
    print(f"\nCluster proper motion means:")
    for name, (pmra, pmdec) in clusters.items():
        print(f"  {name}: pmra={pmra:.1f}, pmdec={pmdec:.1f}")
    
    # Check total synthetic stars
    result = session.execute(text(
        "SELECT COUNT(*) FROM stars "
        "WHERE catalog_source = 'SYNTHETIC_BENCHMARK'"
    ))
    total = result.scalar()
    print(f"\nTotal synthetic stars: {total}")
    
    # Check if ANY star meets discovery thresholds
    result = session.execute(text(
        "SELECT COUNT(*) FROM stars "
        "WHERE catalog_source = 'SYNTHETIC_BENCHMARK' "
        "AND (ruwe > 1.4 OR bp_rp < -0.1 OR bp_rp > 2.8)"
    ))
    print(f"Stars meeting ANY anomaly threshold: {result.scalar()}")
    
    # Sample a few stars
    result = session.execute(text(
        "SELECT source_id, ruwe, bp_rp, pmra, pmdec, phot_g_mean_mag "
        "FROM stars WHERE catalog_source = 'SYNTHETIC_BENCHMARK' LIMIT 5"
    ))
    print(f"\nSample synthetic stars:")
    for row in result:
        print(f"  {row[0]}: RUWE={row[1]:.2f}, BP-RP={row[2]:.2f}, "
              f"pm=({row[3]:.1f}, {row[4]:.1f}), G={row[5]:.2f}")
