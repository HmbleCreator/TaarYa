import uuid

import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from src.api import tess


def request_from(host):
    return Request({"type": "http", "method": "POST", "path": "/api/tess/analyze",
                    "headers": [], "client": (host, 12345), "server": ("test", 80),
                    "scheme": "http", "query_string": b""})


@pytest.fixture(autouse=True)
def reset_rate_limit_state(monkeypatch):
    monkeypatch.setattr(tess, "_RATE_BUCKET_COUNT", 8192)
    monkeypatch.setattr(tess, "_RATE_HASH_KEY", b"test-tess-rate-key")
    monkeypatch.setattr(tess, "_rate_buckets", [None] * tess._RATE_BUCKET_COUNT)


def test_request_schema_bounds_sector_list():
    assert tess.TessAnalysisRequest(tic_id="123", sectors=[1, 32]).tic_id == "123"
    with pytest.raises(ValidationError):
        tess.TessAnalysisRequest(tic_id="123", sectors=[1, 2, 3, 4, 5, 6])
    with pytest.raises(ValidationError):
        tess.TessAnalysisRequest(tic_id="123", sectors=[0])


def test_tess_route_is_exposed_with_json_request_schema():
    app = FastAPI()
    app.include_router(tess.router, prefix="/api")
    operation = app.openapi()["paths"]["/api/tess/analyze"]["post"]
    assert operation["requestBody"]["content"]["application/json"]
    assert "TessAnalysisRequest" in operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]


def test_per_client_rate_budget_is_bounded_and_expires(monkeypatch):
    host = f"192.0.2.{uuid.uuid4().int % 255 + 1}"
    now = [100.0]
    monkeypatch.setattr(tess.time, "monotonic", lambda: now[0])
    assert [tess._claim_request_slot(host) for _ in range(4)] == [True] * 4
    assert tess._claim_request_slot(host) is False
    now[0] += tess._RATE_WINDOW_SECONDS
    assert tess._claim_request_slot(host) is True


def test_client_churn_cannot_reset_a_rate_bucket(monkeypatch):
    monkeypatch.setattr(tess, "_RATE_BUCKET_COUNT", 1)
    monkeypatch.setattr(tess, "_rate_buckets", [None])
    host = "192.0.2.1"
    assert [tess._claim_request_slot(host) for _ in range(4)] == [True] * 4
    assert tess._claim_request_slot("192.0.2.2") is False
    assert tess._claim_request_slot(host) is False


def test_full_analysis_capacity_returns_429_without_calling_archive(monkeypatch):
    host = f"test-{uuid.uuid4()}"
    class Busy:
        @staticmethod
        def acquire(**kwargs):
            return False

    monkeypatch.setattr(tess, "_analysis_slots", Busy())
    monkeypatch.setattr(tess, "analyze_tic", lambda *args: pytest.fail("must not run"))
    with pytest.raises(HTTPException) as error:
        tess.analyze_target(tess.TessAnalysisRequest(tic_id="123"), request_from(host))
    assert error.value.status_code == 429


def test_analysis_errors_are_bounded_and_upstream_detail_is_not_returned(monkeypatch):
    host = f"test-{uuid.uuid4()}"
    monkeypatch.setattr(tess, "analyze_tic", lambda *args: (_ for _ in ()).throw(RuntimeError("secret URL")))
    with pytest.raises(HTTPException) as error:
        tess.analyze_target(tess.TessAnalysisRequest(tic_id="123"), request_from(host))
    assert error.value.status_code == 502
    assert error.value.detail == "TESS analysis could not be completed."
