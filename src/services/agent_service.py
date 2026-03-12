"""Agent service — wraps LLM agent with timeout and error handling."""
import logging
from typing import Optional, List, Dict, Any

from fastapi import HTTPException

logger = logging.getLogger(__name__)


class AgentService:
    """Business logic layer for the TaarYa AI agent."""

    def ask(self, query: str, chat_history: Optional[List[dict]] = None) -> Dict[str, Any]:
        """Send a question to the TaarYa agent and return a structured response."""
        try:
            from src.agent.agent import ask
            result = ask(query, chat_history)
            return result
        except Exception as e:
            logger.error(f"Agent failed: {e}")
            raise HTTPException(status_code=503, detail=f"Agent unavailable: {e}")
