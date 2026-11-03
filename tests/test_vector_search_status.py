from types import SimpleNamespace
from unittest.mock import Mock

from src.database import qdrant_conn
from src.retrieval.vector_search import VectorSearch


def test_missing_papers_collection_is_healthy_but_empty(monkeypatch):
    client = Mock()
    client.get_collections.return_value = SimpleNamespace(collections=[])
    monkeypatch.setattr(qdrant_conn, "get_client", lambda: client)

    status = VectorSearch().get_collection_info()

    assert status == {
        "name": "papers",
        "vectors_count": 0,
        "points_count": 0,
        "status": "connected",
        "exists": False,
    }
    client.get_collection.assert_not_called()


def test_qdrant_probe_failure_is_not_reported_as_empty(monkeypatch):
    client = Mock()
    client.get_collections.side_effect = RuntimeError("Qdrant unavailable")
    monkeypatch.setattr(qdrant_conn, "get_client", lambda: client)

    status = VectorSearch().get_collection_info()

    assert status["status"] == "error"
    assert status["exists"] is False
    assert "Qdrant unavailable" in status["error"]
