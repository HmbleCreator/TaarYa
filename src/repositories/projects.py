"""Persistence operations for research workspaces and saved items."""
import json

from sqlalchemy import text

from src.database import postgres_conn


def list_projects():
    query = text("""
        SELECT p.id, p.name, p.description, p.created_at, p.updated_at,
               COUNT(DISTINCT s.id) AS session_count,
               COUNT(DISTINCT i.id) AS item_count
        FROM research_projects p
        LEFT JOIN chat_sessions s ON s.project_id = p.id
        LEFT JOIN project_items i ON i.project_id = p.id
        GROUP BY p.id ORDER BY p.updated_at DESC, p.name
    """)
    with postgres_conn.session() as db:
        return [dict(row) for row in db.execute(query).mappings().all()]


def create_project(name: str, description: str):
    with postgres_conn.session() as db:
        row = db.execute(text("""
            INSERT INTO research_projects (name, description) VALUES (:name, :description)
            RETURNING id, name, description, created_at, updated_at
        """), {"name": name, "description": description}).mappings().one()
        db.commit()
        return dict(row)


def project_exists(project_id: str) -> bool:
    with postgres_conn.session() as db:
        return db.execute(text("SELECT 1 FROM research_projects WHERE id = :id"), {"id": project_id}).first() is not None


def list_items(project_id: str):
    with postgres_conn.session() as db:
        return [dict(row) for row in db.execute(text("""
            SELECT id, item_type, title, payload, created_at FROM project_items
            WHERE project_id = :project_id ORDER BY created_at DESC
        """), {"project_id": project_id}).mappings().all()]


def create_item(project_id: str, item_type: str, title: str, payload: dict):
    with postgres_conn.session() as db:
        row = db.execute(text("""
            INSERT INTO project_items (project_id, item_type, title, payload)
            VALUES (:project_id, :item_type, :title, CAST(:payload AS JSONB))
            RETURNING id, project_id, item_type, title, payload, created_at
        """), {"project_id": project_id, "item_type": item_type, "title": title,
               "payload": json.dumps(payload)}).mappings().one()
        db.commit()
        return dict(row)


def delete_item(project_id: str, item_id: str) -> bool:
    with postgres_conn.session() as db:
        res = db.execute(text("""
            DELETE FROM project_items
            WHERE id = :item_id AND project_id = :project_id
        """), {"item_id": item_id, "project_id": project_id})
        db.commit()
        return res.rowcount > 0

