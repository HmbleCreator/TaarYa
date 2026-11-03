"""TESS light-curve screening endpoints."""

import hashlib
import logging
import secrets
import threading
import time
from collections import deque
from typing import Annotated

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.services.tess_service import TessAnalysisError, analyze_tic

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tess", tags=["TESS"])
_RATE_WINDOW_SECONDS = 600
_RATE_LIMIT = 4
# Fixed keyed buckets cap memory; hash collisions conservatively share a quota.
_RATE_BUCKET_COUNT = 8192
_RATE_HASH_KEY = secrets.token_bytes(16)
_rate_lock = threading.Lock()
_rate_buckets: list[deque[float] | None] = [None] * _RATE_BUCKET_COUNT
_analysis_slots = threading.BoundedSemaphore(2)


def _claim_request_slot(client: str) -> bool:
    now = time.monotonic()
    digest = hashlib.blake2s(client.encode("utf-8"), key=_RATE_HASH_KEY, digest_size=4).digest()
    bucket_index = int.from_bytes(digest, "big") % _RATE_BUCKET_COUNT
    with _rate_lock:
        requests = _rate_buckets[bucket_index]
        if requests is None:
            requests = _rate_buckets[bucket_index] = deque()
        while requests and now - requests[0] >= _RATE_WINDOW_SECONDS:
            requests.popleft()
        if len(requests) >= _RATE_LIMIT:
            return False
        requests.append(now)
    return True


class TessAnalysisRequest(BaseModel):
    tic_id: Annotated[str, Field(min_length=1, max_length=12)]
    sectors: list[Annotated[int, Field(ge=1, le=999)]] | None = Field(default=None, max_length=5)


@router.post("/analyze")
def analyze_target(body: TessAnalysisRequest, request: Request):
    """Screen public MAST light curves for a periodic transit-like signal."""
    try:
        client = request.client.host if request.client else "unknown"
        if not _claim_request_slot(client):
            raise HTTPException(status_code=429, detail="TESS analysis request limit reached. Try again later.")
        if not _analysis_slots.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="TESS analyses are at capacity. Try again shortly.")
        try:
            return analyze_tic(body.tic_id, body.sectors)
        finally:
            _analysis_slots.release()
    except HTTPException:
        raise
    except TessAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (httpx.HTTPError, TimeoutError) as exc:
        logger.warning("TESS archive request failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="MAST could not provide the requested data.") from exc
    except Exception as exc:
        logger.exception("TESS analysis failed")
        raise HTTPException(status_code=502, detail="TESS analysis could not be completed.") from exc
