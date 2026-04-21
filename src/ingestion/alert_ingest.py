"""
Time-domain alert ingestion from TNS (Transient Name Server) and ALeRCE broker.

Creates Alert graph nodes in Neo4j and links them to nearby stars
via spatial cross-match against the Gaia DR3 catalog in PostgreSQL.

Usage:
    python src/ingestion/alert_ingest.py                      # Default: recent TNS + ALeRCE
    python src/ingestion/alert_ingest.py --source tns         # TNS only
    python src/ingestion/alert_ingest.py --source alerce      # ALeRCE only
    python src/ingestion/alert_ingest.py --days 30            # Last 30 days
    python src/ingestion/alert_ingest.py --dry-run            # Preview without ingesting
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TNS API configuration
# ---------------------------------------------------------------------------
TNS_API_URL = "https://www.wis-tns.org/api/get/search"
TNS_OBJECT_URL = "https://www.wis-tns.org/api/get/object"
TNS_BOT_ID = ""  # Set via --tns-bot-id or TNS_BOT_ID env var
TNS_BOT_NAME = "TaarYa"

# ---------------------------------------------------------------------------
# ALeRCE API configuration
# ---------------------------------------------------------------------------
ALERCE_API_URL = "https://api.alerce.online/alerts/v2"
ALERCE_STAMP_URL = "https://api.alerce.online/stamps/v1"

# Alert classification types of interest
ALERT_CLASSES = [
    "SN",           # Supernovae
    "SN Ia",        # Type Ia supernovae
    "SN II",        # Type II supernovae
    "Nova",         # Classical novae
    "CV",           # Cataclysmic variables
    "AGN",          # Active galactic nuclei
    "Blazar",       # Blazars
    "TDE",          # Tidal disruption events
    "KN",           # Kilonovae
    "SLSN",         # Superluminous supernovae
    "Orphan",       # Orphan afterglows
    "Periodic",     # Periodic variables
    "LPV",          # Long-period variables
    "RRL",          # RR Lyrae
    "CEP",          # Cepheids
    "EB",           # Eclipsing binaries
    "DSCT",         # Delta Scuti
]

# Cross-match radius for linking alerts to Gaia stars (arcsec)
ALERT_CROSSMATCH_RADIUS_ARCSEC = 3.0


def fetch_tns_alerts(
    days: int = 7,
    bot_id: str = "",
    bot_name: str = "TaarYa",
    max_results: int = 200,
) -> list[dict[str, Any]]:
    """
    Fetch recent transient alerts from the Transient Name Server (TNS).

    Args:
        days: Number of days to look back
        bot_id: TNS bot ID for API access
        bot_name: TNS bot name
        max_results: Maximum number of results

    Returns:
        List of alert dicts with keys: name, ra, dec, type, discovery_date, mag, reporter
    """
    alerts = []

    if not bot_id:
        logger.warning(
            "TNS bot_id not set. Using public search (rate-limited). "
            "Set --tns-bot-id or TNS_BOT_ID env var for authenticated access."
        )

    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    headers = {
        "User-Agent": f'tns_marker{{"tns_id": "{bot_id}", "type": "bot", "name": "{bot_name}"}}',
    }

    search_params = {
        "ra": "",
        "dec": "",
        "radius": "",
        "units": "arcsec",
        "objname": "",
        "objname_exact_match": 0,
        "internal_name": "",
        "public_timestamp": since,
        "num_page": max_results,
    }

    try:
        # TNS requires POST with form data
        with httpx.Client(timeout=30.0, headers=headers) as client:
            response = client.post(
                TNS_API_URL,
                data={"api_key": bot_id, "data": str(search_params)},
            )

            if response.status_code == 200:
                data = response.json()
                for item in data.get("data", {}).get("reply", []):
                    alert = {
                        "name": item.get("objname", ""),
                        "ra": float(item.get("ra", 0)),
                        "dec": float(item.get("dec", 0)),
                        "type": item.get("type", "Unknown"),
                        "discovery_date": item.get("discoverydate", ""),
                        "mag": item.get("discoverymag"),
                        "reporter": item.get("reporter", ""),
                        "source": "TNS",
                        "internal_name": item.get("internal_names", ""),
                        "url": f"https://www.wis-tns.org/object/{item.get('objname', '')}",
                    }
                    alerts.append(alert)
                logger.info(f"TNS: fetched {len(alerts)} alerts since {since}")
            elif response.status_code == 429:
                logger.warning("TNS rate limit reached. Try again later or use bot credentials.")
            else:
                logger.warning(f"TNS API returned {response.status_code}: {response.text[:200]}")

    except httpx.TimeoutException:
        logger.warning("TNS API request timed out")
    except Exception as e:
        logger.warning(f"TNS fetch failed: {e}")

    return alerts


def fetch_alerce_alerts(
    days: int = 7,
    max_results: int = 200,
    classes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch recent alerts from the ALeRCE broker (ZTF-based).

    Args:
        days: Number of days to look back
        max_results: Maximum number of results
        classes: Filter by classifier output (e.g., ['SN', 'CV'])

    Returns:
        List of alert dicts with keys: name, ra, dec, type, discovery_date, mag, source
    """
    alerts = []
    since_mjd = _utc_to_mjd(datetime.now(timezone.utc) - timedelta(days=days))

    params: dict[str, Any] = {
        "page": 1,
        "page_size": min(max_results, 100),
        "order_by": "lastmjd",
        "order_mode": "DESC",
        "firstmjd": since_mjd,
    }

    if classes:
        # Filter to specific classifier outputs
        params["classifier"] = "lc_classifier_top"
        params["class"] = classes[0] if len(classes) == 1 else classes

    try:
        with httpx.Client(timeout=30.0) as client:
            total_fetched = 0
            while total_fetched < max_results:
                response = client.get(f"{ALERCE_API_URL}/objects", params=params)

                if response.status_code != 200:
                    logger.warning(f"ALeRCE API returned {response.status_code}")
                    break

                data = response.json()
                items = data.get("items", [])
                if not items:
                    break

                for item in items:
                    alert = {
                        "name": item.get("oid", ""),
                        "ra": float(item.get("meanra", 0)),
                        "dec": float(item.get("meandec", 0)),
                        "type": item.get("class", "Unknown"),
                        "discovery_date": _mjd_to_iso(item.get("firstmjd")),
                        "mag": item.get("first_magpsf_g") or item.get("first_magpsf_r"),
                        "source": "ALeRCE",
                        "ndet": item.get("ndet", 0),
                        "url": f"https://alerce.online/object/{item.get('oid', '')}",
                    }
                    alerts.append(alert)
                    total_fetched += 1

                if total_fetched >= max_results:
                    break

                # Paginate
                params["page"] += 1
                if len(items) < params["page_size"]:
                    break

        logger.info(f"ALeRCE: fetched {len(alerts)} alerts")

    except httpx.TimeoutException:
        logger.warning("ALeRCE API request timed out")
    except Exception as e:
        logger.warning(f"ALeRCE fetch failed: {e}")

    return alerts


def ingest_alerts_to_graph(
    alerts: list[dict[str, Any]],
    crossmatch_radius_arcsec: float = ALERT_CROSSMATCH_RADIUS_ARCSEC,
) -> dict[str, int]:
    """
    Ingest alerts into Neo4j graph and cross-match with Gaia stars.

    Creates:
        - Alert nodes with properties (name, ra, dec, type, discovery_date, mag, source)
        - NEAR_ALERT relationships between Alert and Star nodes within crossmatch radius
        - REPORTED_IN relationships between Alert and Paper nodes mentioning the alert name

    Returns:
        Dict with counts: alerts_created, star_links, paper_links
    """
    from src.database import neo4j_conn, postgres_conn
    from src.retrieval.spatial_search import SpatialSearch

    spatial = SpatialSearch()
    stats = {"alerts_created": 0, "star_links": 0, "paper_links": 0}

    for alert in alerts:
        # Create or merge Alert node
        alert_query = """
        MERGE (a:Alert {name: $name})
        SET a.ra = $ra,
            a.dec = $dec,
            a.type = $type,
            a.discovery_date = $discovery_date,
            a.mag = $mag,
            a.source = $source,
            a.url = $url,
            a.ingested_at = datetime()
        RETURN a
        """
        try:
            with neo4j_conn.session() as session:
                session.run(alert_query, {
                    "name": alert["name"],
                    "ra": alert["ra"],
                    "dec": alert["dec"],
                    "type": alert.get("type", "Unknown"),
                    "discovery_date": alert.get("discovery_date", ""),
                    "mag": alert.get("mag"),
                    "source": alert.get("source", ""),
                    "url": alert.get("url", ""),
                })
                stats["alerts_created"] += 1
        except Exception as e:
            logger.warning(f"Failed to create Alert node for {alert['name']}: {e}")
            continue

        # Cross-match with Gaia stars
        try:
            nearby_stars = spatial.cone_search(
                ra=alert["ra"],
                dec=alert["dec"],
                radius=crossmatch_radius_arcsec / 3600.0,  # Convert arcsec to deg
                limit=5,
            )

            for star in nearby_stars:
                link_query = """
                MATCH (a:Alert {name: $alert_name})
                MATCH (s:Star {source_id: $source_id})
                MERGE (s)-[r:NEAR_ALERT]->(a)
                SET r.separation_arcsec = $sep
                """
                with neo4j_conn.session() as session:
                    session.run(link_query, {
                        "alert_name": alert["name"],
                        "source_id": star["source_id"],
                        "sep": crossmatch_radius_arcsec,
                    })
                    stats["star_links"] += 1

        except Exception as e:
            logger.debug(f"Cross-match failed for {alert['name']}: {e}")

        # Link to papers mentioning this alert
        try:
            paper_link_query = """
            MATCH (a:Alert {name: $alert_name})
            MATCH (p:Paper)
            WHERE toLower(p.title) CONTAINS toLower($alert_name)
               OR toLower(p.abstract) CONTAINS toLower($alert_name)
            MERGE (a)-[:REPORTED_IN]->(p)
            RETURN count(*) as cnt
            """
            with neo4j_conn.session() as session:
                result = session.run(paper_link_query, {"alert_name": alert["name"]})
                record = result.single()
                if record and record["cnt"] > 0:
                    stats["paper_links"] += record["cnt"]
        except Exception:
            pass

    logger.info(
        f"Alert ingestion complete: {stats['alerts_created']} alerts, "
        f"{stats['star_links']} star links, {stats['paper_links']} paper links"
    )
    return stats


def _utc_to_mjd(dt: datetime) -> float:
    """Convert UTC datetime to Modified Julian Date."""
    # MJD epoch: 1858-11-17T00:00:00
    mjd_epoch = datetime(1858, 11, 17, tzinfo=timezone.utc)
    return (dt - mjd_epoch).total_seconds() / 86400.0


def _mjd_to_iso(mjd: float | None) -> str:
    """Convert Modified Julian Date to ISO 8601 string."""
    if mjd is None:
        return ""
    mjd_epoch = datetime(1858, 11, 17, tzinfo=timezone.utc)
    dt = mjd_epoch + timedelta(days=mjd)
    return dt.isoformat()


def print_dry_run(alerts: list[dict], source: str) -> None:
    """Print alert summary without ingesting."""
    print(f"\n{'='*70}")
    print(f"  ALERT INGESTION DRY RUN — {source}")
    print(f"{'='*70}")
    print(f"  Total alerts: {len(alerts)}")
    if alerts:
        types = {}
        for a in alerts:
            t = a.get("type", "Unknown")
            types[t] = types.get(t, 0) + 1
        print(f"  Types: {dict(sorted(types.items(), key=lambda x: -x[1]))}")
        print(f"\n  Sample (first 10):")
        for a in alerts[:10]:
            print(f"    {a['name']:20s}  RA={a['ra']:.4f}  Dec={a['dec']:.4f}  "
                  f"Type={a.get('type','?'):10s}  Mag={a.get('mag','?')}")
    print(f"{'='*70}\n")


def main():
    import os

    parser = argparse.ArgumentParser(description="TaarYa time-domain alert ingestion")
    parser.add_argument(
        "--source",
        choices=["tns", "alerce", "both"],
        default="both",
        help="Alert source (default: both)",
    )
    parser.add_argument("--days", type=int, default=7, help="Look back N days (default: 7)")
    parser.add_argument("--max-results", type=int, default=200, help="Max alerts per source")
    parser.add_argument("--dry-run", action="store_true", help="Preview without ingesting")
    parser.add_argument("--tns-bot-id", default="", help="TNS bot ID for authenticated access")
    parser.add_argument(
        "--crossmatch-radius",
        type=float,
        default=ALERT_CROSSMATCH_RADIUS_ARCSEC,
        help="Cross-match radius in arcsec (default: 3.0)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    bot_id = args.tns_bot_id or os.environ.get("TNS_BOT_ID", "")
    all_alerts: list[dict] = []

    if args.source in ("tns", "both"):
        tns_alerts = fetch_tns_alerts(
            days=args.days, bot_id=bot_id, max_results=args.max_results
        )
        all_alerts.extend(tns_alerts)
        if args.dry_run:
            print_dry_run(tns_alerts, "TNS")

    if args.source in ("alerce", "both"):
        alerce_alerts = fetch_alerce_alerts(
            days=args.days, max_results=args.max_results
        )
        all_alerts.extend(alerce_alerts)
        if args.dry_run:
            print_dry_run(alerce_alerts, "ALeRCE")

    if args.dry_run:
        return

    if not all_alerts:
        logger.info("No alerts fetched. Check network connectivity and API credentials.")
        return

    from src.database import neo4j_conn
    neo4j_conn.connect()

    try:
        stats = ingest_alerts_to_graph(
            all_alerts, crossmatch_radius_arcsec=args.crossmatch_radius
        )
        print(f"\nResult: {stats}")
    finally:
        neo4j_conn.close()


if __name__ == "__main__":
    main()
