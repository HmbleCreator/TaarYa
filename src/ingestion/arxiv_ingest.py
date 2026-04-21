"""
Ingest scientific papers from ArXiv into Qdrant vector database.

Supports large-scale corpus expansion with:
  - 25+ astronomy-targeted query strings
  - Batch upsert (100 pts/request) for throughput
  - Resumable ingestion — skips papers already in Qdrant
  - Per-query progress logging
  - Configurable per-query max results (default 200)
  - Target: 5,000+ papers for production corpus

Usage:
    python src/ingestion/arxiv_ingest.py                    # full ingestion
    python src/ingestion/arxiv_ingest.py --max-results 100  # 100 per query
    python src/ingestion/arxiv_ingest.py --dry-run         # show queries only
"""

from __future__ import annotations

import argparse
import logging
import uuid
from datetime import datetime, timezone

import arxiv
from sentence_transformers import SentenceTransformer
from qdrant_client.http import models

from src.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Query corpus — 25+ targeted queries across stellar astrophysics domains
# ---------------------------------------------------------------------------
# Organized into thematic groups; each group gets max_results papers.
# Total potential: 25 queries × 200 results = 5,000 papers (capped at 200/paper)

ARXIV_QUERY_GROUPS = [
    # --- Gaia & Stellar Catalogues ---
    {
        "category": "Gaia DR3",
        "queries": [
            "Gaia DR3 stellar parameters effective temperature surface gravity",
            "Gaia DR3 radial velocity binary star",
            "Gaia DR3 Hertzsprung Russell diagram open cluster",
            "Gaia eDR3 astrometry parallax metallicity",
            "Gaia DR3 variable stars RR Lyrae Cepheid",
        ],
        "max_results": 200,
    },
    # --- Star Formation & ISM ---
    {
        "category": "Star Formation",
        "queries": [
            "star formation rate molecular cloud protostar",
            "stellar nursery infrared bubbly nebula",
            "outflow jet Herbig-Haro object protoplanetary disk",
            "initial mass function IMF star formation efficiency",
            "YSO young stellar object X-ray emission",
        ],
        "max_results": 200,
    },
    # --- Open Clusters ---
    {
        "category": "Open Clusters",
        "queries": [
            "open cluster membership determination proper motion",
            "Gaia open cluster age determination isochrone fitting",
            "Hyades Pleiades Praesepe star cluster dynamics",
            "white dwarf cluster cooling sequence",
            "cluster initial binary fraction dynamics",
        ],
        "max_results": 200,
    },
    # --- Exoplanets ---
    {
        "category": "Exoplanets",
        "queries": [
            "exoplanet atmosphere transmission spectroscopy JWST HST",
            "exoplanet phase curve thermal emission albedo",
            "exoplanet radius valley super-Earth sub-Neptune",
            "TESS planet detection transit survey",
            "exoplanet habitability zone water content",
        ],
        "max_results": 200,
    },
    # --- Variable Stars ---
    {
        "category": "Variable Stars",
        "queries": [
            "RR Lyrae period metallicity distance ladder",
            "Cepheid period luminosity relation extragalactic distance",
            "delta Scuti pulsating star asteroseismology",
            "Mira variable asymptotic giant branch period-luminosity",
            "cataclysmic variable nova dwarf nova accretion",
        ],
        "max_results": 200,
    },
    # --- Stellar Structure & Evolution ---
    {
        "category": "Stellar Evolution",
        "queries": [
            "stellar evolution tracks MESA stellar structure",
            "asymptotic giant branch thermal pulse dredge-up",
            "core-collapse supernova progenitor massive star",
            "white dwarf crystallization cooling rate",
            "red giant branch bump horizontal branch stellar population",
        ],
        "max_results": 200,
    },
    # --- Milky Way Structure ---
    {
        "category": "Galactic Structure",
        "queries": [
            "Galactic disk warp flare metallicity gradient",
            "Galactic halo substructure stream accretion",
            "solar neighborhood stellar kinematics velocity ellipsoid",
            "galactic bar spiral arm dynamics resonance",
            "globular cluster system galactic formation",
        ],
        "max_results": 200,
    },
    # --- Asteroseismology ---
    {
        "category": "Asteroseismology",
        "queries": [
            "solar-like oscillator granulation p-mode frequency",
            "Kepler asteroseismology red giant core rotation",
            "acoustic oscillation mode lifetime damping rate",
            "stellar activity oscillation frequency modulation",
            "asteroseismic scaling relation solar analogue",
        ],
        "max_results": 200,
    },
    # --- Brown Dwarfs & Substellar ---
    {
        "category": "Brown Dwarfs",
        "queries": [
            "brown dwarf spectral classification L dwarf T dwarf",
            "brown dwarf atmosphere cloudy model retrieved",
            "brown dwarf binary system orbital dynamics",
            "free-floating planet substellar mass function",
            "directly imaged exoplanet companion high contrast",
        ],
        "max_results": 200,
    },
    # --- Stellar Activity ---
    {
        "category": "Stellar Activity",
        "queries": [
            "stellar magnetic activity cycle sunspot flare",
            "coronal mass ejection stellar wind activity",
            "star spot light curve rotation period",
            "plage chromospheric emission activity index",
            "magneto-convection simulation dynamo",
        ],
        "max_results": 200,
    },
]

# Flatten for convenience
ALL_QUERIES = [
    (q["category"], query, q["max_results"])
    for q in ARXIV_QUERY_GROUPS
    for query in q["queries"]
]

# Embedding model configuration (384-dim for all-MiniLM-L6-v2)
EMBEDDING_DIM = 384
PAPERS_COLLECTION = "papers"
BATCH_SIZE = 100


def _get_paper_id(arxiv_id: str) -> str:
    """Convert arxiv_id to a stable UUID string for Qdrant."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, arxiv_id))


def _already_indexed(client, point_ids: list[str]) -> set[str]:
    """Return subset of point_ids that already exist in Qdrant."""
    if not point_ids:
        return set()
    try:
        result = client.retrieve(collection_name=PAPERS_COLLECTION, ids=point_ids)
        return {r.id for r in result}
    except Exception:
        return set()


def _ensure_collection(client) -> None:
    """Create the papers collection if it doesn't already exist."""
    existing = [c.name for c in client.get_collections().collections]
    if PAPERS_COLLECTION in existing:
        logger.info(f"Collection '{PAPERS_COLLECTION}' already exists")
        return
    client.create_collection(
        collection_name=PAPERS_COLLECTION,
        vectors_config=models.VectorParams(
            size=EMBEDDING_DIM,
            distance=models.Distance.COSINE,
        ),
    )
    logger.info(f"Created collection '{PAPERS_COLLECTION}' with {EMBEDDING_DIM}d vectors")


def _build_point(star: dict) -> models.PointStruct:
    """Build a Qdrant PointStruct from a paper result."""
    return models.PointStruct(
        id=star["id"],
        vector=star["vector"],
        payload=star["payload"],
    )


def ingest_arxiv_papers(
    qdrant_conn,
    max_per_query: int = 200,
    total_target: int = 5000,
    skip_existing: bool = True,
) -> dict:
    """
    Ingest papers from ArXiv into Qdrant.

    Args:
        qdrant_conn: Qdrant connection/client manager
        max_per_query: Maximum results to fetch per query (default 200)
        total_target: Stop ingestion after this many new papers (default 5000)
        skip_existing: Skip papers already indexed in Qdrant

    Returns:
        dict with keys: total_inserted, queries_processed, skipped_duplicates, elapsed_s
    """
    logger.info(f"Initializing embedding model: {settings.embedding_model}")
    embedder = SentenceTransformer(settings.embedding_model)

    client = qdrant_conn.get_client()
    _ensure_collection(client)

    total_inserted = 0
    queries_processed = 0
    skipped_duplicates = 0
    batch: list[dict] = []
    start_time = datetime.now(timezone.utc)

    for category, query, group_max in ALL_QUERIES:
        if total_inserted >= total_target:
            logger.info(f"Target of {total_target} papers reached, stopping.")
            break

        effective_max = min(max_per_query, group_max)
        batch_flush_count = 0

        try:
            logger.info(f"[{category}] Searching: '{query}' (max {effective_max})")
            arxiv_client = arxiv.Client()
            search = arxiv.Search(
                query=query,
                max_results=effective_max,
                sort_by=arxiv.SortCriterion.Relevance,
            )

            inserted_this_query = 0

            for paper in arxiv_client.results(search):
                if total_inserted >= total_target:
                    break

                arxiv_id = paper.entry_id.split("/abs/")[-1]
                point_id = _get_paper_id(arxiv_id)

                if skip_existing:
                    already = _already_indexed(client, [point_id])
                    if point_id in already:
                        skipped_duplicates += 1
                        continue

                title = paper.title
                authors = [a.name for a in paper.authors[:3]]
                abstract = paper.summary
                published = paper.published.isoformat() if paper.published else None
                categories = list(paper.categories)

                text_to_embed = f"{title}. {abstract}"
                embedding = embedder.encode(text_to_embed).tolist()

                point = {
                    "id": point_id,
                    "vector": embedding,
                    "payload": {
                        "title": title,
                        "authors": authors,
                        "abstract": abstract,
                        "arxiv_id": arxiv_id,
                        "published": published,
                        "categories": categories,
                        "query_category": category,
                        "ingested_at": datetime.now(timezone.utc).isoformat(),
                    },
                }
                batch.append(point)

                if len(batch) >= BATCH_SIZE:
                    client.upsert(
                        collection_name=PAPERS_COLLECTION,
                        points=[_build_point(p) for p in batch],
                    )
                    total_inserted += len(batch)
                    batch_flush_count += len(batch)
                    inserted_this_query += len(batch)
                    logger.info(
                        f"  → Flushed {len(batch)}-pt batch "
                        f"(total inserted: {total_inserted})"
                    )
                    batch = []

            queries_processed += 1

        except Exception as e:
            logger.warning(f"Error searching ArXiv for '{query}': {e}")
            continue

    if batch:
        client.upsert(
            collection_name=PAPERS_COLLECTION,
            points=[_build_point(p) for p in batch],
        )
        total_inserted += len(batch)

    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

    logger.info(
        f"ArXiv ingestion complete in {elapsed:.1f}s: "
        f"{total_inserted} new papers inserted, "
        f"{skipped_duplicates} duplicates skipped, "
        f"{queries_processed} queries processed"
    )

    return {
        "total_inserted": total_inserted,
        "queries_processed": queries_processed,
        "skipped_duplicates": skipped_duplicates,
        "elapsed_s": round(elapsed, 2),
    }


def print_dry_run() -> None:
    """Print the query plan without ingesting anything."""
    print(f"\n{'='*70}")
    print("  ARXIV INGESTION DRY RUN — Query Plan")
    print(f"{'='*70}")
    total_queries = sum(len(g["queries"]) for g in ARXIV_QUERY_GROUPS)
    max_total = total_queries * 200
    print(f"  Categories:     {len(ARXIV_QUERY_GROUPS)}")
    print(f"  Total queries: {total_queries}")
    print(f"  Max results/query: 200")
    print(f"  Theoretical max papers: {max_total}")
    print(f"  Ingestion target: 5,000")
    print(f"{'='*70}\n")
    for group in ARXIV_QUERY_GROUPS:
        print(f"  [{group['category']}]")
        for q in group["queries"]:
            print(f"    • {q}")
        print()


def main():
    parser = argparse.ArgumentParser(description="TaarYa ArXiv corpus expansion")
    parser.add_argument(
        "--max-results",
        type=int,
        default=200,
        help="Max results per query (default 200)",
    )
    parser.add_argument(
        "--target",
        type=int,
        default=5000,
        help="Stop after N new papers (default 5000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show query plan and exit without ingesting",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Re-embed and overwrite existing papers",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if args.dry_run:
        print_dry_run()
        return

    from src.database import qdrant_conn

    qdrant_conn.connect()
    try:
        result = ingest_arxiv_papers(
            qdrant_conn,
            max_per_query=args.max_results,
            total_target=args.target,
            skip_existing=not args.no_skip_existing,
        )
        print(f"\nResult: {result}")
    finally:
        qdrant_conn.close()


if __name__ == "__main__":
    main()
