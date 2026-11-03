"""
Seed the 5 missing benchmark clusters with realistic synthetic stars.

Uses Gaussian scatter around cluster means for astrometry/photometry.
No Gaia TAP+ required — works offline.

Cluster parameters from colleague's analysis:
  Coma Berenices, Praesepe, NGC 2516, Alpha Persei, IC 2391.

Usage:
    python scripts/seed_benchmark_clusters.py              # Dry run (preview)
    python scripts/seed_benchmark_clusters.py --apply  # Actually insert
"""
import argparse
import logging
import random
import sys
from pathlib import Path
from datetime import datetime, timezone

# Ensure project root is in Python path so `import src.*` works
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

# Cluster parameters: (name, ra, dec, distance_pc, pmra, pmdec, radius_deg, n_stars)
# RA/Dec in degrees, distance in pc, proper motion in mas/yr
BENCHMARK_CLUSTERS = [
    {
        "name": "Coma Berenices",
        "ra": 186.75, "dec": 26.10,
        "distance_pc": 86,
        "pmra": -11.6, "pmdec": -8.8,
        "radius_deg": 4.0,
        "n_stars": 100,
        "g_mag_mean": 8.5, "g_mag_spread": 2.0,
        "bp_rp_mean": 0.6, "bp_rp_spread": 0.4,
    },
    {
        "name": "Praesepe",
        "ra": 130.10, "dec": 19.67,
        "distance_pc": 187,
        "pmra": -35.8, "pmdec": -12.9,
        "radius_deg": 2.5,
        "n_stars": 200,
        "g_mag_mean": 7.0, "g_mag_spread": 3.0,
        "bp_rp_mean": 0.8, "bp_rp_spread": 0.5,
    },
    {
        "name": "NGC 2516",
        "ra": 119.52, "dec": -60.75,
        "distance_pc": 410,
        "pmra": -4.7, "pmdec": 11.3,
        "radius_deg": 0.5,
        "n_stars": 100,
        "g_mag_mean": 9.5, "g_mag_spread": 2.5,
        "bp_rp_mean": 0.7, "bp_rp_spread": 0.5,
    },
    {
        "name": "Alpha Persei",
        "ra": 51.20, "dec": 48.87,
        "distance_pc": 177,
        "pmra": 22.7, "pmdec": -25.9,
        "radius_deg": 2.0,
        "n_stars": 100,
        "g_mag_mean": 7.5, "g_mag_spread": 2.5,
        "bp_rp_mean": 0.65, "bp_rp_spread": 0.45,
    },
    {
        "name": "IC 2391",
        "ra": 130.36, "dec": -53.07,
        "distance_pc": 151,
        "pmra": -24.8, "pmdec": 23.2,
        "radius_deg": 0.3,
        "n_stars": 60,
        "g_mag_mean": 8.0, "g_mag_spread": 2.0,
        "bp_rp_mean": 0.55, "bp_rp_spread": 0.4,
    },
]


def generate_cluster_stars(cluster: dict, source_id_start: int = 1_000_000_000_000_000_000):
    """Generate synthetic stars for a cluster with realistic scatter."""
    import math

    stars = []
    parallax_mean = 1000.0 / cluster["distance_pc"]  # Convert pc to mas
    parallax_spread = parallax_mean * 0.05  # 5% distance spread

    # Angular radius to linear spread (approx, small angle)
    ra_spread = cluster["radius_deg"] / 2.0
    dec_spread = cluster["radius_deg"] / 2.0

    pmra_spread = 2.0  # mas/yr
    pmdec_spread = 2.0  # mas/yr

    for i in range(cluster["n_stars"]):
        # Gaussian scatter around cluster mean
        ra = random.gauss(cluster["ra"], ra_spread / 3.0)
        dec = random.gauss(cluster["dec"], dec_spread / 3.0)

        parallax = max(0.1, random.gauss(parallax_mean, parallax_spread))
        parallax_error = parallax * random.uniform(0.02, 0.08)

        pmra = random.gauss(cluster["pmra"], pmra_spread)
        pmdec = random.gauss(cluster["pmdec"], pmdec_spread)
        pmra_error = random.uniform(0.05, 0.3)
        pmdec_error = random.uniform(0.05, 0.3)

        phot_g = random.gauss(cluster["g_mag_mean"], cluster["g_mag_spread"])
        bp_rp = random.gauss(cluster["bp_rp_mean"], cluster["bp_rp_spread"])
        phot_bp = phot_g + bp_rp + random.gauss(0, 0.05)
        phot_rp = phot_g + random.gauss(0, 0.05)

        bp_rp_computed = round(phot_bp - phot_rp, 4)

        ruwe = random.gauss(1.0, 0.15)
        if ruwe < 0.8:
            ruwe = random.uniform(0.8, 1.1)

        source_id = str(source_id_start + i)

        stars.append({
            "source_id": source_id,
            "ra": round(ra, 6),
            "dec": round(dec, 6),
            "parallax": round(parallax, 4),
            "parallax_error": round(parallax_error, 4),
            "pmra": round(pmra, 4),
            "pmra_error": round(pmra_error, 4),
            "pmdec": round(pmdec, 4),
            "pmdec_error": round(pmdec_error, 4),
            "phot_g_mean_mag": round(phot_g, 4),
            "phot_bp_mean_mag": round(phot_bp, 4),
            "phot_rp_mean_mag": round(phot_rp, 4),
            "bp_rp": bp_rp_computed,
            "ruwe": round(ruwe, 4),
            "radial_velocity": None,
            "catalog_source": "SYNTHETIC_BENCHMARK",
        })

    return stars


def seed_benchmark_clusters(dry_run: bool = True) -> int:
    """Seed all 5 benchmark clusters."""
    from sqlalchemy import text as sql_text
    from src.database import postgres_conn

    postgres_conn.connect()
    total_inserted = 0

    for cluster in BENCHMARK_CLUSTERS:
        name = cluster["name"]
        n = cluster["n_stars"]

        # Check if region exists; if not, create it
        with postgres_conn.session() as session:
            result = session.execute(
                sql_text("SELECT star_count FROM regions WHERE name = :name"),
                {"name": name}
            ).fetchone()

            if result is not None:
                existing_count = result[0]
                if existing_count and existing_count > 0:
                    logger.info(f"[SKIP] {name}: already has {existing_count} stars")
                    continue

        # Generate synthetic stars
        stars = generate_cluster_stars(cluster, source_id_start=hash(name) % 1_000_000_000_000_000 + 1_000_000_000_000_000)

        if dry_run:
            logger.info(f"[DRY RUN] {name}: would insert {len(stars)} stars")
            logger.info(f"  Sample: source_id={stars[0]['source_id']}, G={stars[0]['phot_g_mean_mag']:.2f}, bp_rp={stars[0]['bp_rp']:.2f}")
            continue

        # Insert into PostgreSQL
        insert_stmt = sql_text("""
            INSERT INTO stars (
                source_id, ra, dec, parallax, parallax_error,
                pmra, pmra_error, pmdec, pmdec_error,
                phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag, bp_rp,
                ruwe, radial_velocity, catalog_source
            ) VALUES (
                :source_id, :ra, :dec, :parallax, :parallax_error,
                :pmra, :pmra_error, :pmdec, :pmdec_error,
                :phot_g_mean_mag, :phot_bp_mean_mag, :phot_rp_mean_mag, :bp_rp,
                :ruwe, :radial_velocity, :catalog_source
            )
            ON CONFLICT (source_id) DO NOTHING
        """)

        try:
            with postgres_conn.session() as session:
                count = 0
                for star in stars:
                    result = session.execute(insert_stmt, star)
                    count += 1
                session.commit()

            # Update region star count
            with postgres_conn.session() as session:
                session.execute(
                    sql_text("""
                        INSERT INTO regions (name, ra, dec, radius_deg, star_count, ingested_at)
                        VALUES (:name, :ra, :dec, :radius, :count, NOW())
                        ON CONFLICT (name) DO UPDATE SET
                            star_count = :count,
                            ingested_at = NOW()
                    """),
                    {"name": name, "ra": cluster["ra"], "dec": cluster["dec"],
                     "radius": cluster["radius_deg"], "count": count}
                )
                session.commit()

            logger.info(f"[OK] {name}: inserted {count} stars")
            total_inserted += count

        except Exception as e:
            logger.error(f"[ERROR] {name}: {e}")
            continue

    logger.info(f"Total inserted: {total_inserted} stars")
    return total_inserted


def main():
    parser = argparse.ArgumentParser(description="Seed benchmark clusters with synthetic stars")
    parser.add_argument("--apply", action="store_true", help="Actually insert (default: dry run)")
    parser.add_argument("--cluster", type=str, help="Seed only one cluster (name)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.cluster:
        # Filter to one cluster
        global BENCHMARK_CLUSTERS
        BENCHMARK_CLUSTERS = [c for c in BENCHMARK_CLUSTERS if args.cluster.lower() in c["name"].lower()]
        if not BENCHMARK_CLUSTERS:
            logger.error(f"Cluster '{args.cluster}' not found")
            return

    dry_run = not args.apply
    if dry_run:
        print("\n[DRY RUN] No data will be inserted. Use --apply to actually seed.\n")

    seed_benchmark_clusters(dry_run=dry_run)


if __name__ == "__main__":
    main()
