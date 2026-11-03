"""Chat session API routes."""
from fastapi import APIRouter, Query
from sqlalchemy import text

from src.database import postgres_conn

router = APIRouter(prefix="/sessions", tags=["Sessions"])


@router.post("")
async def create_session(project_id: str | None = Query(default=None)):
    """Create a chat session, optionally attached to a research project."""
    query = text("""
        INSERT INTO chat_sessions (title, project_id)
        VALUES (NULL, :project_id)
        RETURNING id
    """)
    with postgres_conn.session() as session:
        row = session.execute(query, {"project_id": project_id}).mappings().one()
        session.commit()
    return {"session_id": str(row["id"])}


@router.get("")
async def list_sessions(project_id: str | None = Query(default=None)):
    """Return sessions, optionally scoped to one project."""
    query = text("""
        SELECT
            s.id,
            s.title,
            s.updated_at,
            (
                SELECT LEFT(m.content, 60)
                FROM chat_messages m
                WHERE m.session_id = s.id
                ORDER BY m.created_at DESC
                LIMIT 1
            ) AS last_message
        FROM chat_sessions s
        WHERE (:project_id IS NULL OR s.project_id = :project_id)
        ORDER BY s.updated_at DESC
    """)
    with postgres_conn.session() as session:
        rows = session.execute(query, {"project_id": project_id}).mappings().all()
    return [
        {
            "id": str(row["id"]),
            "title": row["title"],
            "updated_at": row["updated_at"],
            "last_message": row["last_message"],
        }
        for row in rows
    ]


@router.get("/{session_id}/messages")
async def list_messages(session_id: str):
    """Return all messages for a session in chronological order."""
    query = text("""
        SELECT id, role, content, tool_trace, created_at
        FROM chat_messages
        WHERE session_id = :session_id
        ORDER BY created_at ASC
    """)
    with postgres_conn.session() as session:
        rows = session.execute(query, {"session_id": session_id}).mappings().all()
    return [
        {
            "id": str(row["id"]),
            "role": row["role"],
            "content": row["content"],
            "tool_trace": row["tool_trace"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """Delete a chat session and its messages."""
    query = text("DELETE FROM chat_sessions WHERE id = :session_id")
    with postgres_conn.session() as session:
        session.execute(query, {"session_id": session_id})
        session.commit()
    return {"ok": True}
