"""Vector similarity search using Qdrant."""
import logging
from typing import List, Optional, Dict, Any

from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue
)

from src.database import qdrant_conn
from src.config import settings

logger = logging.getLogger(__name__)

# Lazy-load the embedding model to avoid slow import at module level
_embedding_model = None


def _get_embedding_model():
    """Lazy-load sentence-transformers model."""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        logger.info(f"Loading embedding model: {settings.embedding_model}")
        _embedding_model = SentenceTransformer(settings.embedding_model)
        logger.info("Embedding model loaded")
    return _embedding_model


class VectorSearch:
    """Qdrant-powered semantic similarity search."""
    
    DEFAULT_COLLECTION = "papers"
    VECTOR_SIZE = 384  # all-MiniLM-L6-v2 dimension
    
    def ensure_collection(
        self,
        name: Optional[str] = None,
        vector_size: int = VECTOR_SIZE
    ) -> None:
        """
        Create a Qdrant collection if it doesn't exist.
        
        Args:
            name: Collection name (defaults to 'papers')
            vector_size: Dimensionality of vectors
        """
        name = name or self.DEFAULT_COLLECTION
        client = qdrant_conn.get_client()
        
        collections = client.get_collections().collections
        existing = [c.name for c in collections]
        
        if name not in existing:
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=Distance.COSINE
                )
            )
            logger.info(f"Created Qdrant collection: {name}")
        else:
            logger.debug(f"Collection {name} already exists")
    
    def embed_text(self, text: str) -> List[float]:
        """
        Generate embedding for a text string.
        
        Args:
            text: Input text to embed
            
        Returns:
            Embedding vector as list of floats
        """
        model = _get_embedding_model()
        embedding = model.encode(text)
        return embedding.tolist()
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts efficiently.
        
        Args:
            texts: List of input texts
            
        Returns:
            List of embedding vectors
        """
        model = _get_embedding_model()
        embeddings = model.encode(texts, show_progress_bar=len(texts) > 100)
        return embeddings.tolist()
    
    def index_documents(
        self,
        documents: List[Dict[str, Any]],
        collection: Optional[str] = None
    ) -> int:
        """
        Index documents into Qdrant.
        
        Each document should have:
            - id: unique identifier (int)
            - text: content to embed
            - metadata: dict of extra fields (title, arxiv_id, etc.)
        
        Args:
            documents: List of document dicts
            collection: Collection name
            
        Returns:
            Number of documents indexed
        """
        collection = collection or self.DEFAULT_COLLECTION
        self.ensure_collection(collection)
        
        client = qdrant_conn.get_client()
        
        # Generate embeddings
        texts = [doc["text"] for doc in documents]
        embeddings = self.embed_batch(texts)
        
        # Build points
        points = []
        for doc, embedding in zip(documents, embeddings):
            point = PointStruct(
                id=doc["id"],
                vector=embedding,
                payload=doc.get("metadata", {})
            )
            points.append(point)
        
        # Upsert in batches of 100
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            client.upsert(
                collection_name=collection,
                points=batch
            )
        
        logger.info(f"Indexed {len(points)} documents into '{collection}'")
        return len(points)
    
    def search_similar(
        self,
        query_text: str,
        collection: Optional[str] = None,
        limit: int = 10,
        score_threshold: Optional[float] = None,
        filter_by: Optional[Dict[str, str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Semantic search: embed query and find similar documents.
        
        Args:
            query_text: Natural language query
            collection: Collection to search
            limit: Number of results
            score_threshold: Minimum similarity score (0-1)
            filter_by: Optional metadata filters {field: value}
            
        Returns:
            List of results with score, id, and payload
        """
        collection = collection or self.DEFAULT_COLLECTION
        client = qdrant_conn.get_client()
        
        # Check collection exists before searching
        try:
            collections = client.get_collections().collections
            if collection not in [c.name for c in collections]:
                logger.warning(f"Collection '{collection}' not found — no documents indexed yet")
                return []
        except Exception as e:
            logger.error(f"Failed to check collections: {e}")
            return []
        
        # Embed the query
        query_vector = self.embed_text(query_text)
        
        # Build filter if specified
        qdrant_filter = None
        if filter_by:
            conditions = [
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in filter_by.items()
            ]
            qdrant_filter = Filter(must=conditions)
        
        # Search
        results = client.search(
            collection_name=collection,
            query_vector=query_vector,
            query_filter=qdrant_filter,
            limit=limit,
            score_threshold=score_threshold
        )
        
        # Format results
        hits = []
        for result in results:
            hits.append({
                "id": result.id,
                "score": result.score,
                "payload": result.payload
            })
        
        logger.info(f"Vector search: {len(hits)} results for '{query_text[:50]}...'")
        return hits
    
    def search_by_vector(
        self,
        vector: List[float],
        collection: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search by pre-computed vector.
        
        Args:
            vector: Query vector
            collection: Collection name
            limit: Number of results
            
        Returns:
            List of results with score and payload
        """
        collection = collection or self.DEFAULT_COLLECTION
        client = qdrant_conn.get_client()
        
        results = client.search(
            collection_name=collection,
            query_vector=vector,
            limit=limit
        )
        
        return [
            {"id": r.id, "score": r.score, "payload": r.payload}
            for r in results
        ]
    
    def get_collection_info(self, collection: Optional[str] = None) -> Dict[str, Any]:
        """Get collection statistics."""
        collection = collection or self.DEFAULT_COLLECTION
        client = qdrant_conn.get_client()
        
        try:
            info = client.get_collection(collection)
            return {
                "name": collection,
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": info.status.value if info.status else "unknown"
            }
        except Exception:
            return {"name": collection, "exists": False}
