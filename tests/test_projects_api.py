import pytest
from fastapi import HTTPException
from src.api import projects

def test_delete_project_item_not_found(monkeypatch):
    # project does not exist
    monkeypatch.setattr(projects.repository, "project_exists", lambda pid: False)
    with pytest.raises(HTTPException) as exc:
        projects.delete_project_item("proj-1", "item-1")
    assert exc.value.status_code == 404

def test_delete_project_item_item_not_found(monkeypatch):
    # project exists but item not found
    monkeypatch.setattr(projects.repository, "project_exists", lambda pid: True)
    monkeypatch.setattr(projects.repository, "delete_item", lambda pid, iid: False)
    with pytest.raises(HTTPException) as exc:
        projects.delete_project_item("proj-1", "item-1")
    assert exc.value.status_code == 404

def test_delete_project_item_success(monkeypatch):
    # success
    monkeypatch.setattr(projects.repository, "project_exists", lambda pid: True)
    monkeypatch.setattr(projects.repository, "delete_item", lambda pid, iid: True)
    res = projects.delete_project_item("proj-1", "item-1")
    assert res == {"status": "success", "deleted_item_id": "item-1"}

