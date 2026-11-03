"""Research project API."""
import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.repositories import projects as repository

router = APIRouter(prefix="/projects", tags=["Projects"])
logger = logging.getLogger(__name__)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class ProjectItemCreate(BaseModel):
    item_type: Literal["search", "star", "paper", "region"]
    title: str = Field(min_length=1, max_length=240)
    payload: dict[str, Any] = Field(default_factory=dict)


@router.get("")
def get_projects():
    try:
        return repository.list_projects()
    except Exception as exc:
        logger.exception("Could not list research projects")
        raise HTTPException(status_code=503, detail="Projects are temporarily unavailable") from exc


@router.post("", status_code=201)
def post_project(body: ProjectCreate):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Project name cannot be blank")
    try:
        return repository.create_project(name, body.description.strip())
    except Exception as exc:
        logger.exception("Could not create research project")
        raise HTTPException(status_code=503, detail="Project could not be created") from exc


@router.get("/{project_id}/items")
def get_project_items(project_id: str):
    try:
        if not repository.project_exists(project_id):
            raise HTTPException(status_code=404, detail="Project not found")
        return repository.list_items(project_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Could not load project items")
        raise HTTPException(status_code=503, detail="Project items are temporarily unavailable") from exc


@router.post("/{project_id}/items", status_code=201)
def post_project_item(project_id: str, body: ProjectItemCreate):
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Saved item title cannot be blank")
    try:
        if not repository.project_exists(project_id):
            raise HTTPException(status_code=404, detail="Project not found")
        return repository.create_item(project_id, body.item_type, title, body.payload)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Could not save project item")
        raise HTTPException(status_code=503, detail="Item could not be saved") from exc


@router.delete("/{project_id}/items/{item_id}", status_code=200)
def delete_project_item(project_id: str, item_id: str):
    try:
        if not repository.project_exists(project_id):
            raise HTTPException(status_code=404, detail="Project not found")
        deleted = repository.delete_item(project_id, item_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Item not found")
        return {"status": "success", "deleted_item_id": item_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Could not delete project item")
        raise HTTPException(status_code=503, detail="Item could not be deleted") from exc

