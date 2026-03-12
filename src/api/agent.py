"""Agent query API route — includes SSE streaming endpoint."""
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from src.services.agent_service import AgentService
from src.schemas import AskRequest

router = APIRouter(prefix="/agent", tags=["Agent"])
_svc = AgentService()


@router.post("/ask")
async def ask_agent(request: AskRequest):
    """
    Ask TaarYa a natural language astronomy question.

    The agent will understand your query, select the right tools
    (spatial search, paper search, graph traversal), run them,
    and synthesize a response.
    """
    return _svc.ask(request.query, request.chat_history)


@router.get("/ask")
async def ask_agent_get(
    q: str = Query(..., min_length=3, description="Your astronomy question"),
):
    """Ask TaarYa (GET version for quick queries)."""
    return _svc.ask(q)


@router.post("/ask/stream")
async def ask_agent_stream(request: AskRequest):
    """
    Ask TaarYa with Server-Sent Events streaming.

    Emits real-time events as the agent processes:
      - thinking: agent is reasoning
      - tool_start: a tool invocation begins (name, input)
      - tool_end: a tool invocation finishes (output_preview)
      - answer: final synthesized response
      - done: stream complete
    """
    from src.agent.streaming import run_agent_streaming

    return StreamingResponse(
        run_agent_streaming(request.query, request.chat_history),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
