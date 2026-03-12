"""TaarYa Astronomy Agent - LLM-powered query routing and response generation."""
import asyncio
import json
import logging
import re
from threading import Thread
from typing import Any, Dict, Optional

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import text

from src.agent.tools import (
    ALL_TOOLS,
    cone_search,
    get_catalog_coverage_raw,
    semantic_search,
    star_lookup,
)
from src.config import settings
from src.database import postgres_conn

logger = logging.getLogger(__name__)

MAX_AGENT_ITERATIONS = 3
MAX_AGENT_EXECUTION_TIME = 30

BASE_SYSTEM_PROMPT = """You are TaarYa, an expert and enthusiastic astronomy assistant.
Your goal is to help users explore the cosmos using real data from Gaia, arXiv, and other sources.

You have access to tools that query real astronomical databases:
1. **get_catalog_coverage** - Return the exact RA/Dec bounds of the currently loaded catalog
2. **cone_search** - Find stars near a sky coordinate (RA/Dec)
3. **star_lookup** - Get details about a specific star by its Gaia source ID
4. **find_nearby_stars** - Find neighbors of a known star
5. **semantic_search** - Search research papers by topic
6. **graph_query** - Explore the knowledge graph for star-paper relationships
7. **count_stars_in_region** - Count stars in a sky area

Guidelines:
- Be conversational and remember previous interactions.
- Use the live coverage block above as the source of truth for where star data exists right now.
- Never guess famous astronomy coordinates from prior knowledge if they are outside the loaded bounds.
- If a requested coordinate is outside coverage, explain that the current database does not contain that region.
- When users mention coordinates, use cone_search.
  - If they only give RA, assume Dec=0.
  - If they give a star identifier, use star_lookup.
- Summarize findings clearly and briefly.
- If you find 20 or fewer stars, list all of them in a markdown table.
- Use tools whenever real data is needed.
- If there are no grounded results, say so plainly instead of filling the gap with general astronomy knowledge.

Coordinates are in degrees (RA: 0-360, Dec: -90 to +90).
"""


async def build_system_prompt() -> str:
    """Build a session prompt with live catalog coverage injected at the top."""
    coverage = await asyncio.to_thread(get_catalog_coverage_raw)
    center = coverage.get("suggested_search_center") or {}
    center_ra = center.get("ra")
    center_dec = center.get("dec")

    coverage_block = (
        "CURRENT DATABASE STATE (live, do not ignore):\n"
        "----------------------------------------\n"
        f"Stars loaded: {coverage['total_stars']}\n"
        f"RA range: {coverage['ra_min']}° to {coverage['ra_max']}°\n"
        f"Dec range: {coverage['dec_min']}° to {coverage['dec_max']}°\n"
        f"Suggested search center: RA {center_ra}°, Dec {center_dec}°\n"
        "----------------------------------------"
    )
    return f"{coverage_block}\n\n{BASE_SYSTEM_PROMPT}"


def build_system_prompt_sync() -> str:
    """Bridge the async prompt builder into sync agent entry points."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(build_system_prompt())

    result_holder: Dict[str, str] = {}
    error_holder: Dict[str, Exception] = {}

    def _runner():
        try:
            result_holder["prompt"] = asyncio.run(build_system_prompt())
        except Exception as exc:  # pragma: no cover - defensive bridge
            error_holder["error"] = exc

    thread = Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if "error" in error_holder:
        raise error_holder["error"]
    return result_holder["prompt"]


def _run_async_sync(coro):
    """Bridge async DB helpers into the current sync agent path."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result_holder: Dict[str, Any] = {}
    error_holder: Dict[str, Exception] = {}

    def _runner():
        try:
            result_holder["result"] = asyncio.run(coro)
        except Exception as exc:  # pragma: no cover - defensive bridge
            error_holder["error"] = exc

    thread = Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if "error" in error_holder:
        raise error_holder["error"]
    return result_holder.get("result")


async def load_session_history(session_id: str) -> list:
    """Load last 10 message pairs for a session as LangChain messages."""
    if not session_id:
        return []
    query = text("""
        SELECT role, content FROM chat_messages
        WHERE session_id = :session_id
        ORDER BY created_at DESC
        LIMIT 20
    """)
    with postgres_conn.session() as session:
        rows = session.execute(query, {"session_id": session_id}).mappings().all()
    rows = list(reversed(rows))
    result = []
    for row in rows:
        if row["role"] == "user":
            result.append(HumanMessage(content=row["content"]))
        else:
            result.append(AIMessage(content=row["content"]))
    return result


async def save_message(session_id: str, role: str, content: str, tool_trace: dict = None):
    if not session_id:
        return
    msg_query = text("""
        INSERT INTO chat_messages (session_id, role, content, tool_trace)
        VALUES (:session_id, :role, :content, :tool_trace)
    """)
    title_query = text("""
        UPDATE chat_sessions
        SET title = COALESCE(title, LEFT(:content, 50)),
            updated_at = NOW()
        WHERE id = :session_id
    """)
    with postgres_conn.session() as session:
        session.execute(msg_query, {
            "session_id": session_id,
            "role": role,
            "content": content,
            "tool_trace": json.dumps(tool_trace) if tool_trace else None
        })
        if role == "user":
            session.execute(title_query, {
                "session_id": session_id,
                "content": content
            })
        session.commit()


_title_llm = None


async def generate_session_title(session_id: str, query: str, answer: str):
    """Generate a short descriptive title from the first exchange."""
    if not session_id:
        return

    check = text("SELECT title FROM chat_sessions WHERE id = :sid")
    with postgres_conn.session() as s:
        row = s.execute(check, {"sid": session_id}).mappings().one_or_none()
        if not row or row["title"] is not None:
            return

    prompt = (
        f"Give a 5-7 word title for a conversation that started with: "
        f"'{query[:120]}'. Reply with only the title, no punctuation."
    )

    try:
        global _title_llm
        if _title_llm is None:
            _title_llm = _get_llm()

        response = _title_llm.invoke([HumanMessage(content=prompt)])
        title = str(response.content).strip()[:60]
        update = text("UPDATE chat_sessions SET title = :title WHERE id = :sid")
        with postgres_conn.session() as s:
            s.execute(update, {"title": title, "sid": session_id})
            s.commit()
    except Exception:
        pass


def _parse_tool_output(tool_output: Any) -> Optional[Any]:
    """Extract structured tool payloads for the frontend when possible."""
    if isinstance(tool_output, (list, dict)):
        return tool_output

    if isinstance(tool_output, str):
        raw = tool_output.strip()
        if raw.startswith("[") or raw.startswith("{"):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None

    return None


def _get_llm():
    """Create the appropriate LLM based on configuration."""
    if settings.openai_api_key and settings.openai_api_key != "your-openai-key-here":
        try:
            from langchain_openai import ChatOpenAI

            logger.info("Using OpenAI LLM")
            return ChatOpenAI(
                api_key=settings.openai_api_key,
                model="gpt-4o-mini",
                temperature=0,
            )
        except Exception as e:
            logger.warning(f"OpenAI init failed: {e}, falling back to Ollama")

    try:
        from langchain_community.chat_models import ChatOllama

        logger.info(f"Using Ollama LLM ({settings.ollama_model})")
        return ChatOllama(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            temperature=0,
        )
    except ImportError:
        pass

    try:
        from langchain.chat_models import ChatOllama

        logger.info(f"Using Ollama LLM ({settings.ollama_model})")
        return ChatOllama(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            temperature=0,
        )
    except (ImportError, Exception):
        pass

    raise RuntimeError(
        "No LLM available. Either set OPENAI_API_KEY in .env "
        "or install and run Ollama (ollama serve) with a model "
        f"(ollama pull {settings.ollama_model})"
    )


class AstronomyAgent:
    """The TaarYa agent that understands astronomy queries and uses tools."""

    def __init__(self):
        self._agent = None
        self._llm = None
        self._system_prompt: Optional[str] = None

    def _ensure_agent(self, system_prompt: str):
        """Initialize or refresh the agent when the live prompt changes."""
        if self._agent is not None and self._system_prompt == system_prompt:
            return

        if self._llm is None:
            self._llm = _get_llm()
        self._system_prompt = system_prompt

        try:
            from langchain.agents import AgentType, initialize_agent

            self._agent = initialize_agent(
                tools=ALL_TOOLS,
                llm=self._llm,
                agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
                verbose=True,
                max_iterations=MAX_AGENT_ITERATIONS,
                max_execution_time=MAX_AGENT_EXECUTION_TIME,
                handle_parsing_errors=True,
                return_intermediate_steps=True,
                agent_kwargs={"prefix": system_prompt},
            )
            logger.info("Agent initialized (ReAct mode)")
        except Exception as e:
            logger.error(f"Failed to initialize agent: {e}")
            raise

    def ask(self, query: str, chat_history: Optional[list] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Process a natural language astronomy query."""
        system_prompt = build_system_prompt_sync()
        self._ensure_agent(system_prompt)

        history_messages = _run_async_sync(load_session_history(session_id)) if session_id else []
        if not history_messages and chat_history:
            for msg in chat_history:
                role = msg.get("role")
                content = msg.get("content")
                if role in ("human", "user"):
                    history_messages.append(HumanMessage(content=content))
                elif role in ("ai", "assistant"):
                    history_messages.append(AIMessage(content=content))

        try:
            context_query = query
            if history_messages and hasattr(self._agent, "agent") and not hasattr(self._agent.agent, "runnable"):
                history_text = "\n".join(
                    f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {m.content}"
                    for m in history_messages[-6:]
                )
                context_query = f"Previous Conversation:\n{history_text}\n\nCurrent Question: {query}"

            result = self._agent.invoke({
                "input": context_query,
                "chat_history": history_messages,
            })

            steps = result.get("intermediate_steps", [])
            tools_used = []
            tool_outputs = []

            for step in steps:
                if hasattr(step[0], "tool"):
                    tool_name = step[0].tool
                    tool_input = str(step[0].tool_input)
                    tool_output = step[1]

                    tools_used.append({
                        "tool": tool_name,
                        "input": tool_input,
                        "output_preview": str(tool_output)[:200],
                    })

                    structured_output = _parse_tool_output(tool_output)
                    if structured_output is not None:
                        tool_outputs.append({
                            "tool": tool_name,
                            "data": structured_output,
                        })

            answer = result.get("output", "I couldn't generate a response.")
            tool_trace = {"tools_used": tools_used, "tool_outputs": tool_outputs}
            _run_async_sync(save_message(session_id, "user", query))
            _run_async_sync(save_message(session_id, "assistant", answer, tool_trace))
            _run_async_sync(generate_session_title(session_id, query, answer))
            return {
                "answer": answer,
                "tools_used": tools_used,
                "tool_outputs": tool_outputs,
                "query": query,
            }
        except Exception as e:
            logger.error(f"Agent error: {e}")
            fallback = self._fallback_response(query)
            _run_async_sync(save_message(session_id, "user", query))
            _run_async_sync(save_message(session_id, "assistant", fallback["answer"], {"tools_used": fallback.get("tools_used", [])}))
            _run_async_sync(generate_session_title(session_id, query, fallback["answer"]))
            return fallback

    def _fallback_response(self, query: str) -> Dict[str, Any]:
        """Simple fallback when LLM is unavailable."""
        query_lower = query.lower()
        tools_used = []
        response_parts = []

        ra_match = re.search(r"ra\s*[=:]\s*([\d.]+)", query_lower)
        dec_match = re.search(r"dec\s*[=:]\s*([+-]?[\d.]+)", query_lower)

        if ra_match and dec_match:
            ra = float(ra_match.group(1))
            dec = float(dec_match.group(1))
            result = cone_search.invoke({"ra": ra, "dec": dec, "radius_deg": 0.5, "limit": 10})
            tools_used.append({"tool": "cone_search", "input": f"ra={ra}, dec={dec}"})
            response_parts.append(result)

        id_match = re.search(r"(?:source_id|star|id)\s*[=:]\s*(\d+)", query_lower)
        if id_match:
            sid = id_match.group(1)
            result = star_lookup.invoke({"source_id": sid})
            tools_used.append({"tool": "star_lookup", "input": sid})
            response_parts.append(result)

        if any(word in query_lower for word in ["paper", "research", "study", "published"]):
            result = semantic_search.invoke({"query": query, "limit": 5})
            tools_used.append({"tool": "semantic_search", "input": query})
            response_parts.append(result)

        if not response_parts:
            response_parts.append(
                "I couldn't connect to an LLM for reasoning. "
                "Please try a more specific query with coordinates (RA/Dec) "
                "or a star source_id, or ensure Ollama is running."
            )

        return {
            "answer": "\n\n".join(response_parts),
            "tools_used": tools_used,
            "query": query,
            "mode": "fallback (no LLM)",
        }


_agent = None


def ask(query: str, chat_history: Optional[list] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
    """Convenience function to ask the TaarYa agent a question."""
    global _agent
    if _agent is None:
        _agent = AstronomyAgent()
    return _agent.ask(query, chat_history, session_id)
