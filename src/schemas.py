"""Pydantic response schemas for TaarYa API."""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


# ── Star Schemas ────────────────────────────────────────────

class StarResponse(BaseModel):
    """A single star record from the Gaia catalog."""
    source_id: str
    ra: Optional[float] = None
    dec: Optional[float] = None
    parallax: Optional[float] = None
    pmra: Optional[float] = None
    pmdec: Optional[float] = None
    phot_g_mean_mag: Optional[float] = None
    phot_bp_mean_mag: Optional[float] = None
    phot_rp_mean_mag: Optional[float] = None
    catalog_source: Optional[str] = None
    angular_distance: Optional[float] = None


class ConeSearchQuery(BaseModel):
    ra: float
    dec: float
    radius_deg: float


class ConeSearchResponse(BaseModel):
    """Response for cone search queries."""
    query: ConeSearchQuery
    count: int
    stars: List[StarResponse]


class StarCountResponse(BaseModel):
    """Response for region star count."""
    ra: float
    dec: float
    radius_deg: float
    count: int


class NearbyStarsResponse(BaseModel):
    """Response for nearby-stars lookup."""
    source_id: str
    radius_deg: float
    count: int
    neighbors: List[StarResponse]


# ── Paper Schemas ───────────────────────────────────────────

class PaperResponse(BaseModel):
    """A single paper record."""
    arxiv_id: Optional[str] = None
    title: Optional[str] = None
    authors: Optional[str] = None
    abstract: Optional[str] = None
    categories: Optional[str] = None
    published_date: Optional[str] = None
    score: Optional[float] = None


class PaperSearchResponse(BaseModel):
    """Response for paper search queries."""
    query: str
    count: int
    results: List[Dict[str, Any]]


class PaperTopicResponse(BaseModel):
    """Response for topic-based paper search."""
    keyword: str
    count: int
    papers: List[Dict[str, Any]]


class PapersByStarResponse(BaseModel):
    """Response for papers-by-star lookup."""
    source_id: str
    count: int
    papers: List[Dict[str, Any]]


# ── Agent Schemas ───────────────────────────────────────────

class AskRequest(BaseModel):
    """Request body for the /ask endpoint."""
    query: str = Field(..., min_length=1)
    chat_history: Optional[List[dict]] = None
    session_id: Optional[str] = None


class AgentResponse(BaseModel):
    """Response from the TaarYa agent."""
    answer: Optional[str] = None
    tool_results: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None


# ── System Schemas ──────────────────────────────────────────

class BackendStatus(BaseModel):
    """Status of a single backend."""
    status: str = "unknown"
    error: Optional[str] = None


class PostgresStats(BackendStatus):
    total_stars: Optional[int] = 0


class QdrantStats(BackendStatus):
    name: Optional[str] = None
    vectors_count: Optional[int] = None
    points_count: Optional[int] = None
    exists: Optional[bool] = None


class Neo4jStats(BackendStatus):
    stars: Optional[int] = 0
    papers: Optional[int] = 0
    clusters: Optional[int] = 0
    relationships: Optional[int] = 0


class StatsResponse(BaseModel):
    """System-wide statistics from all backends."""
    postgresql: Optional[Dict[str, Any]] = None
    qdrant: Optional[Dict[str, Any]] = None
    neo4j: Optional[Dict[str, Any]] = None


# ── Error Schema ────────────────────────────────────────────

class ErrorResponse(BaseModel):
    """Standard error response."""
    detail: str
    status_code: int = 500
