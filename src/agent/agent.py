"""TaarYa Astronomy Agent - LLM-powered query routing and response generation."""
import asyncio
import json
import logging
import re
import uuid
from threading import Thread
from typing import Any, Dict, Optional

from sqlalchemy import text

from src.agent.langchain_compat import build_agent_executor
from src.agent.runtime_shims import AIMessage, HumanMessage
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

MAX_AGENT_ITERATIONS = 5
MAX_AGENT_EXECUTION_TIME = 90

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
- If the user did NOT provide coordinates or a source_id and you need a sky location, call get_catalog_coverage first.
- For exploratory requests like "surprise me" or "show me something interesting", stay inside the returned coverage bounds and prefer the suggested_search_center instead of inventing coordinates.
- When users mention coordinates, use cone_search.
  - If they only give RA, assume Dec=0.
  - If they give a star identifier, use star_lookup.
- Summarize findings clearly and briefly.
- **IMPORTANT**: When stars are returned with "discovery_score", always mention why they are interesting (e.g., high RUWE, color extremes) and prioritize listing the top-scoring candidates.
- If you find 20 or fewer stars, list all of them in a markdown table.
- Use tools whenever real data is needed.
- If there are no grounded results, say so plainly instead of filling the gap with general astronomy knowledge.

Coordinates are in degrees (RA: 0-360, Dec: -90 to +90).

CRITICAL TOOL USE RULES:
1. After generating your "Action" JSON block, you MUST immediately STOP generating text. DO NOT generate the "Observation:" block yourself. The system will provide the Observation.
2. DO NOT hallucinate, invent, or make up data for tool outputs. Only use the real data returned in the explicit Observation.
3. You MUST call Final Answer as your last action. After gathering data from 2-3 tool calls, always synthesize and call Final Answer — do not keep calling more tools.
4. Minimize tool calls, but NEVER skip coverage grounding. If the user did not provide coordinates or a source_id and you need a sky position, your first tool call MUST be get_catalog_coverage before any cone_search.
"""

SKY_EXPLORATION_TERMS = (
    "surprise",
    "interesting",
    "catalog",
    "star",
    "stars",
    "sky",
    "region",
    "nearby",
    "object",
    "objects",
    "source",
    "sources",
    "solar twin",
    "show me",
    "find",
    "explore",
    "search",
)

LITERATURE_TERMS = (
    "paper",
    "papers",
    "research",
    "study",
    "studies",
    "arxiv",
    "literature",
    "publication",
    "publications",
)


def _format_coverage_window(coverage: Dict[str, Any]) -> str:
    """Return a concise RA/Dec summary for the current catalog footprint."""
    if not coverage or not coverage.get("total_stars"):
        return "no star catalog coverage is currently loaded"
    return (
        f"RA {coverage['ra_min']}° to {coverage['ra_max']}° and "
        f"Dec {coverage['dec_min']}° to {coverage['dec_max']}°"
    )


def _query_has_explicit_catalog_target(query: str) -> bool:
    """Detect whether the user already supplied a concrete sky target."""
    query_lower = query.lower()
    if re.search(r"\bra\s*[:=]?\s*[+-]?\d", query_lower) and re.search(r"\bdec\s*[:=]?\s*[+-]?\d", query_lower):
        return True
    if re.search(r"\bsource_id\b", query_lower):
        return True
    if re.search(r"\b(?:star|source|id)\s*[:=]\s*\d{4,}\b", query_lower):
        return True
    return False


def _query_is_literature_focused(query: str) -> bool:
    """Detect broad literature requests that do not need sky coverage grounding."""
    query_lower = query.lower()
    return any(term in query_lower for term in LITERATURE_TERMS)


def _query_needs_catalog_grounding(query: str) -> bool:
    """Return True for broad sky exploration queries that need live coverage first."""
    if _query_has_explicit_catalog_target(query) or _query_is_literature_focused(query):
        return False
    query_lower = query.lower()
    return any(term in query_lower for term in SKY_EXPLORATION_TERMS)


def _ground_query_to_catalog(query: str) -> str:
    """Inject turn-level grounding instructions for vague sky exploration requests."""
    if not _query_needs_catalog_grounding(query):
        return query

    coverage = get_catalog_coverage_raw()
    if not coverage.get("total_stars"):
        return query

    center = coverage.get("suggested_search_center") or {}
    center_ra = center.get("ra")
    center_dec = center.get("dec")
    guidance_lines = [
        "GROUNDING DIRECTIVE FOR THIS TURN:",
        "- The user did not provide explicit coordinates or a source_id.",
        "- Your first tool call must be get_catalog_coverage before any cone_search.",
        f"- The loaded catalog footprint currently spans {_format_coverage_window(coverage)}.",
    ]
    if center_ra is not None and center_dec is not None:
        guidance_lines.append(
            f"- If you need a starting point, use the suggested in-bounds center RA {center_ra}°, Dec {center_dec}°."
        )
    guidance_lines.extend(
        [
            "- Do not probe famous or memorized coordinates unless the returned coverage includes them.",
            "- For exploratory requests, stay inside the loaded footprint and keep the search grounded.",
        ]
    )
    return f"{query}\n\n" + "\n".join(guidance_lines)


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


def _coverage_followup_hint(coverage: Dict[str, Any]) -> str:
    """Return a concise next-step hint anchored to the loaded footprint."""
    if not coverage or not coverage.get("total_stars"):
        return "Load a catalog first, then ask me to explore a region."

    center = coverage.get("suggested_search_center") or {}
    center_ra = center.get("ra")
    center_dec = center.get("dec")
    if center_ra is None or center_dec is None:
        return "Ask me to explore within the currently loaded footprint."
    return f"Ask me to explore near RA {center_ra}°, Dec {center_dec}° or another point inside the loaded footprint."


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


def _normalize_session_id(session_id: Optional[str]) -> Optional[str]:
    """Accept only UUID-backed session identifiers used by the chat tables."""
    if not session_id:
        return None

    try:
        return str(uuid.UUID(str(session_id)))
    except (ValueError, TypeError, AttributeError):
        logger.warning("Ignoring invalid session_id value that is not a UUID: %r", session_id)
        return None


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


def _normalize_agent_answer(answer: Any) -> str:
    """Unwrap structured-chat final answer JSON into plain text."""
    if answer is None:
        return "I couldn't generate a response."

    if not isinstance(answer, str):
        return str(answer)

    raw = answer.strip()
    if not raw:
        return "I couldn't generate a response."

    if not (raw.startswith("{") and raw.endswith("}")):
        return raw

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw

    if payload.get("action") != "Final Answer":
        return raw

    final_answer = payload.get("action_input")
    if isinstance(final_answer, str) and final_answer.strip():
        return final_answer.strip()
    return raw


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
            self._agent = build_agent_executor(
                tools=ALL_TOOLS,
                llm=self._llm,
                system_prompt=system_prompt,
                max_iterations=MAX_AGENT_ITERATIONS,
                max_execution_time=MAX_AGENT_EXECUTION_TIME,
                handle_parsing_errors=True,
                return_intermediate_steps=True,
            )
            logger.info("Agent initialized")
        except Exception as e:
            logger.error(f"Failed to initialize agent: {e}")
            raise

    def ask(self, query: str, chat_history: Optional[list] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Process a natural language astronomy query."""
        system_prompt = build_system_prompt_sync()
        self._ensure_agent(system_prompt)
        session_id = _normalize_session_id(session_id)

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
            context_query = _ground_query_to_catalog(context_query)

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

            answer = _normalize_agent_answer(result.get("output", "I couldn't generate a response."))
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
