"""
Ingest scientific papers from ArXiv into Qdrant vector database.
"""

import logging
import uuid

import arxiv
from sentence_transformers import SentenceTransformer
from qdrant_client.http import models

from src.config import settings

logger = logging.getLogger(__name__)

# ArXiv search queries
ARXIV_QUERIES = [
    "Gaia DR3 stellar catalog astrometry",
    "star formation rate molecular cloud collapse",
    "exoplanet transmission spectroscopy atmosphere JWST",
    "RR Lyrae Cepheid variable star light curve",
    "open cluster proper motion membership Gaia",
    "brown dwarf spectral classification",
    "stellar kinematics Milky Way disk",
]

# Embedding model configuration (384-dim for all-MiniLM-L6-v2)
EMBEDDING_DIM = 384
PAPERS_COLLECTION = "papers"


def _get_paper_id(arxiv_id: str) -> str:
    """Convert arxiv_id to a stable UUID string for Qdrant."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, arxiv_id))


def ingest_arxiv_papers(qdrant_conn, max_papers: int = 300) -> None:
    """
    Ingest papers from ArXiv into Qdrant.

    Args:
        qdrant_conn: Qdrant connection/client manager
        max_papers: Maximum number of papers to ingest per query
    """
    try:
        # Initialize embedding model
        logger.info(f"Initializing embedding model: {settings.embedding_model}")
        embedder = SentenceTransformer(settings.embedding_model)

        # Get the Qdrant client
        client = qdrant_conn.get_client()

        # Check if collection exists, create if not
        existing_collections = [c.name for c in client.get_collections().collections]
        if PAPERS_COLLECTION not in existing_collections:
            logger.info(f"Creating papers collection '{PAPERS_COLLECTION}'")
            client.create_collection(
                collection_name=PAPERS_COLLECTION,
                vectors_config=models.VectorParams(
                    size=EMBEDDING_DIM,
                    distance=models.Distance.COSINE,
                ),
            )
        else:
            logger.info(f"Papers collection '{PAPERS_COLLECTION}' already exists")

        total_inserted = 0

        # Search each query
        for query in ARXIV_QUERIES:
            if total_inserted >= 300:
                logger.info("Reached 300 paper cap, stopping ingestion")
                break
            try:
                inserted_for_query = 0
                logger.info(f"Searching ArXiv for: '{query}'")

                # Create client and search
                arxiv_client = arxiv.Client()
                search = arxiv.Search(
                    query=query,
                    max_results=100,
                    sort_by=arxiv.SortCriterion.Relevance,
                )

                for paper in arxiv_client.results(search):
                    if total_inserted >= 300:
                        break
                    try:
                        arxiv_id = paper.entry_id.split("/abs/")[-1]
                        point_id = _get_paper_id(arxiv_id)

                        # Check if paper already exists
                        existing = client.retrieve(
                            collection_name=PAPERS_COLLECTION,
                            ids=[point_id],
                        )
                        if existing:
                            logger.debug(f"Paper {arxiv_id} already exists, skipping")
                            continue

                        # Extract data
                        title = paper.title
                        authors = [author.name for author in paper.authors[:3]]
                        abstract = paper.summary
                        published = (
                            paper.published.isoformat() if paper.published else None
                        )
                        categories = paper.categories

                        # Generate embedding from title and abstract
                        text_to_embed = f"{title}. {abstract}"
                        embedding = embedder.encode(text_to_embed).tolist()

                        # Upsert to Qdrant
                        client.upsert(
                            collection_name=PAPERS_COLLECTION,
                            points=[
                                models.PointStruct(
                                    id=point_id,
                                    vector=embedding,
                                    payload={
                                        "title": title,
                                        "authors": authors,
                                        "abstract": abstract,
                                        "arxiv_id": arxiv_id,
                                        "published": published,
                                        "categories": categories,
                                    },
                                )
                            ],
                        )

                        inserted_for_query += 1
                        total_inserted += 1

                    except Exception as e:
                        logger.warning(
                            f"Error processing paper from query '{query}': {e}"
                        )
                        continue

                logger.info(f"Query '{query}': inserted {inserted_for_query} papers")

            except Exception as e:
                logger.warning(f"Error searching ArXiv for '{query}': {e}")
                continue

        logger.info(f"ArXiv ingestion complete: {total_inserted} papers inserted")

    except Exception as e:
        logger.error(f"Critical error in ArXiv ingestion: {e}", exc_info=True)


if __name__ == "__main__":
    from src.database import qdrant_conn

    qdrant_conn.connect()
    ingest_arxiv_papers(qdrant_conn)
    qdrant_conn.close()
