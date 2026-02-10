"""Agent query API route."""
from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter(prefix="/agent", tags=["Agent"])


class AskRequest(BaseModel):
    """Request body for the /ask endpoint."""
    query: str
    chat_history: Optional[List[dict]] = None


@router.post("/ask")
async def ask_agent(request: AskRequest):
    """
    Ask TaarYa a natural language astronomy question.
    
    The agent will understand your query, select the right tools 
    (spatial search, paper search, graph traversal), run them,
    and synthesize a response.
    
    Example queries:
    - "Show me bright stars near RA=45, Dec=0.5"
    - "How many stars are within 1 degree of the galactic center?"
    - "Find research papers about stellar evolution"
    """
    from src.agent.agent import ask
    result = ask(request.query, request.chat_history)
    return result


@router.get("/ask")
async def ask_agent_get(
    q: str = Query(..., min_length=3, description="Your astronomy question"),
):
    """Ask TaarYa (GET version for quick queries)."""
    from src.agent.agent import ask
    result = ask(q)
    return result
