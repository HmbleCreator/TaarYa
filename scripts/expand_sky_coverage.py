"""
Expand TaarYa's sky coverage beyond the initial 8 clusters.

Adds 20+ additional regions spanning a broad range of astrophysical
environments: globular clusters, OB associations, star-forming regions,
nearby moving groups, and high-latitude calibration fields.

Usage:
    python scripts/expand_sky_coverage.py                # Seed all new regions
    python scripts/expand_sky_coverage.py --dry-run      # Preview regions
    python scripts/expand_sky_coverage.py --fetch-gaia   # Also fetch Gaia stars per region
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

from sqlalchemy import text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Extended region catalog
# ---------------------------------------------------------------------------
# Format: (name, ra_deg, dec_deg, radius_deg, description, region_type)
# Coordinates from: SIMBAD, WEBDA, Dias+ (2021), Cantat-Gaudin+ (2020)
#
# Types: OC = open cluster, GC = globular cluster, OB = OB association,
#        SFR = star-forming region, MG = moving group, CAL = calibration field

EXTENDED_REGIONS = [
    # --- Globular Clusters ---
    ("47 Tucanae",       6.024,  -72.081, 0.5,  "NGC 104, one of the brightest GCs, ~4.5 kpc", "GC"),
    ("Omega Centauri",  201.697, -47.480, 0.9,  "NGC 5139, most massive MW GC, ~5.4 kpc", "GC"),
    ("M13",             250.423,  36.460, 0.3,  "NGC 6205, Great Hercules Cluster, ~7.1 kpc", "GC"),
    ("M3",              205.548,  28.377, 0.3,  "NGC 5272, Canes Venatici GC, ~10.2 kpc", "GC"),
    ("M92",             259.281,  43.136, 0.2,  "NGC 6341, metal-poor GC, ~8.3 kpc", "GC"),
    ("M4",              245.897, -26.526, 0.4,  "NGC 6121, nearest GC, ~2.2 kpc", "GC"),
    ("NGC 6752",        287.717, -59.985, 0.3,  "Southern GC, ~4.0 kpc, core-collapsed", "GC"),

    # --- OB Associations ---
    ("Scorpius OB2",    243.0,   -23.0,   8.0,  "Upper Sco + Upper CrA + Lower Cen-Crux, ~140 pc", "OB"),
    ("Cygnus OB2",      308.3,    41.3,   1.0,  "Massive OB assoc in Cygnus, ~1.4 kpc", "OB"),
    ("Vela OB2",        128.5,   -44.0,   3.0,  "Near Vela SNR, ~400 pc", "OB"),
    ("Cepheus OB3",     343.0,    62.0,   2.0,  "Northern OB assoc, ~800 pc", "OB"),

    # --- Star-Forming Regions ---
    ("Taurus SFR",       68.0,    25.0,   5.0,  "Taurus-Auriga molecular cloud complex, ~140 pc", "SFR"),
    ("rho Ophiuchi",    246.8,   -24.5,   2.0,  "L1688 dark cloud complex, ~138 pc", "SFR"),
    ("Chamaeleon I",    167.0,   -77.0,   1.5,  "Cha I dark cloud, ~160 pc", "SFR"),
    ("Serpens Main",    277.5,     1.2,   0.5,  "Serpens molecular cloud core, ~436 pc", "SFR"),
    ("NGC 2264",        100.2,     9.9,   0.5,  "Cone Nebula / Christmas Tree cluster, ~760 pc", "SFR"),

    # --- Nearby Moving Groups ---
    ("AB Doradus MG",    82.2,   -65.4,   3.0,  "AB Dor moving group, ~20 pc, ~120 Myr", "MG"),
    ("Beta Pic MG",      86.8,   -51.1,   3.0,  "Beta Pictoris moving group, ~35 pc, ~24 Myr", "MG"),
    ("TW Hydrae",       165.5,   -34.7,   2.0,  "TW Hya association, ~60 pc, ~10 Myr", "MG"),
    ("Tucana-Horologium",  15.0,  -60.0,   5.0,  "Tuc-Hor moving group, ~45 pc, ~45 Myr", "MG"),

    # --- Additional Open Clusters ---
    ("NGC 752",          29.2,    37.8,   0.5,  "Andromeda OC, ~450 pc, ~1.1 Gyr", "OC"),
    ("NGC 6819",        295.3,    40.2,   0.2,  "Kepler field OC, ~2.4 kpc, ~2.5 Gyr", "OC"),
    ("M67",             132.8,    11.8,   0.3,  "NGC 2682, solar-metallicity benchmark, ~900 pc", "OC"),
    ("NGC 6811",        294.3,    46.4,   0.2,  "Kepler field OC, ~1.2 kpc, ~1 Gyr", "OC"),
    ("Blanco 1",          1.0,   -30.0,   0.7,  "Southern OC, ~240 pc, ~100 Myr", "OC"),
    ("Trumpler 14",     160.9,   -59.6,   0.1,  "Carina Nebula young cluster, ~2.8 kpc", "OC"),

    # --- Calibration / High-Latitude Fields ---
    ("North Galactic Pole",  192.86,  27.13,  2.0,  "High-lat calibration field, low extinction", "CAL"),
    ("South Galactic Pole",    0.80, -27.13,  2.0,  "High-lat calibration field, low extinction", "CAL"),
    ("Kepler Field Center",  290.7,   44.5,   5.0,  "Kepler/K2 prime field, rich asteroseismic data", "CAL"),
    ("TESS CVZ North",       270.0,   66.5,   3.0,  "TESS continuous viewing zone, longest baselines", "CAL"),
]


def seed_extended_regions(dry_run: bool = False) -> int:
    """Seed extended regions into PostgreSQL and Neo4j."""
    if dry_run:
        _print_dry_run()
        return 0

    from src.database import postgres_conn, neo4j_conn
    from src.retrieval.graph_search import GraphSearch

    postgres_conn.connect()
    neo4j_conn.connect()
    graph = GraphSearch()

    count = 0
    for name, ra, dec, radius, desc, rtype in EXTENDED_REGIONS:
        # Upsert into PostgreSQL regions table
        stmt = text("""
            INSERT INTO regions (name, ra, dec, radius_deg, star_count, ingested_at)
            VALUES (:name, :ra, :dec, :radius, 0, NOW())
            ON CONFLICT (name) DO UPDATE SET
                ra = EXCLUDED.ra,
                dec = EXCLUDED.dec,
                radius_deg = EXCLUDED.radius_deg
        """)
        try:
            with postgres_conn.session() as session:
                session.execute(stmt, {"name": name, "ra": ra, "dec": dec, "radius": radius})
                session.commit()
        except Exception as e:
            logger.warning(f"Failed to upsert region {name}: {e}")
            continue

        # Create Cluster node in Neo4j
        try:
            graph.create_cluster_node(name=name, ra=ra, dec=dec)
        except Exception as e:
            logger.warning(f"Failed to create Neo4j node for {name}: {e}")

        logger.info(f"Seeded [{rtype}] {name} (RA={ra:.2f}, Dec={dec:.2f}, r={radius}°)")
        count += 1

    logger.info(f"Seeded {count} extended regions")
    return count


def fetch_gaia_for_regions(max_stars_per_region: int = 500) -> int:
    """Fetch Gaia DR3 stars for each extended region via TAP+ (astroquery)."""
    try:
        from astroquery.gaia import Gaia
    except ImportError:
        logger.error("astroquery not installed. Run: pip install astroquery")
        return 0

    from src.database import postgres_conn
    from sqlalchemy import text as sql_text

    postgres_conn.connect()
    total_fetched = 0

    for name, ra, dec, radius, _desc, _rtype in EXTENDED_REGIONS:
        logger.info(f"Fetching Gaia DR3 stars for {name} (r={radius}°)...")

        adql = f"""
        SELECT TOP {max_stars_per_region}
            source_id, ra, dec, parallax, parallax_error,
            pmra, pmdec, phot_g_mean_mag, bp_rp,
            ruwe, radial_velocity
        FROM gaiadr3.gaia_source
        WHERE 1=CONTAINS(
            POINT('ICRS', ra, dec),
            CIRCLE('ICRS', {ra}, {dec}, {radius})
        )
        AND parallax IS NOT NULL
        AND phot_g_mean_mag IS NOT NULL
        ORDER BY phot_g_mean_mag ASC
        """

        try:
            job = Gaia.launch_job_async(adql)
            results = job.get_results()

            if len(results) == 0:
                logger.info(f"  No stars found for {name}")
                continue

            # Insert into PostgreSQL
            insert_stmt = sql_text("""
                INSERT INTO stars (source_id, ra, dec, parallax, parallax_error,
                                   pmra, pmdec, phot_g_mean_mag, bp_rp,
                                   ruwe, radial_velocity, catalog_source)
                VALUES (:source_id, :ra, :dec, :parallax, :parallax_error,
                        :pmra, :pmdec, :phot_g_mean_mag, :bp_rp,
                        :ruwe, :radial_velocity, 'GAIA_DR3')
                ON CONFLICT (source_id) DO NOTHING
            """)

            with postgres_conn.session() as session:
                for row in results:
                    session.execute(insert_stmt, {
                        "source_id": str(row["source_id"]),
                        "ra": float(row["ra"]),
                        "dec": float(row["dec"]),
                        "parallax": float(row["parallax"]) if row["parallax"] else None,
                        "parallax_error": float(row["parallax_error"]) if row["parallax_error"] else None,
                        "pmra": float(row["pmra"]) if row["pmra"] else None,
                        "pmdec": float(row["pmdec"]) if row["pmdec"] else None,
                        "phot_g_mean_mag": float(row["phot_g_mean_mag"]) if row["phot_g_mean_mag"] else None,
                        "bp_rp": float(row["bp_rp"]) if row["bp_rp"] else None,
                        "ruwe": float(row["ruwe"]) if row["ruwe"] else None,
                        "radial_velocity": float(row["radial_velocity"]) if row["radial_velocity"] else None,
                    })
                session.commit()

            total_fetched += len(results)
            logger.info(f"  Inserted {len(results)} stars for {name}")

            # Update region star count
            with postgres_conn.session() as session:
                session.execute(
                    sql_text("UPDATE regions SET star_count = :count WHERE name = :name"),
                    {"count": len(results), "name": name},
                )
                session.commit()

        except Exception as e:
            logger.warning(f"  Gaia TAP query failed for {name}: {e}")
            continue

    logger.info(f"Total new stars fetched: {total_fetched}")
    return total_fetched


def _print_dry_run() -> None:
    """Preview extended regions."""
    print(f"\n{'='*80}")
    print("  EXTENDED SKY COVERAGE — Region Plan")
    print(f"{'='*80}")
    print(f"  Total new regions: {len(EXTENDED_REGIONS)}")

    by_type: dict[str, list] = {}
    for name, ra, dec, radius, desc, rtype in EXTENDED_REGIONS:
        by_type.setdefault(rtype, []).append((name, ra, dec, radius, desc))

    type_labels = {
        "GC": "Globular Clusters",
        "OB": "OB Associations",
        "SFR": "Star-Forming Regions",
        "MG": "Moving Groups",
        "OC": "Open Clusters",
        "CAL": "Calibration Fields",
    }

    for rtype, regions in by_type.items():
        print(f"\n  [{type_labels.get(rtype, rtype)}] ({len(regions)} regions)")
        for name, ra, dec, radius, desc in regions:
            print(f"    {name:22s}  RA={ra:7.2f}  Dec={dec:+7.2f}  r={radius:4.1f}°  {desc}")

    print(f"\n{'='*80}\n")


def main():
    parser = argparse.ArgumentParser(description="TaarYa extended sky coverage")
    parser.add_argument("--dry-run", action="store_true", help="Preview regions without seeding")
    parser.add_argument("--fetch-gaia", action="store_true",
                        help="Also fetch Gaia DR3 stars via TAP+ (requires internet)")
    parser.add_argument("--max-stars", type=int, default=500,
                        help="Max stars per region from Gaia TAP (default: 500)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.dry_run:
        _print_dry_run()
        return

    count = seed_extended_regions()
    print(f"\nSeeded {count} extended regions")

    if args.fetch_gaia:
        stars = fetch_gaia_for_regions(max_stars_per_region=args.max_stars)
        print(f"Fetched {stars} Gaia DR3 stars across extended regions")


if __name__ == "__main__":
    main()
