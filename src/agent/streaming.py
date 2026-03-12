"""Streaming agent — SSE endpoint that emits real-time tool events."""
import json
import logging
from typing import Optional, List, Any
from queue import Queue, Empty
from threading import Thread

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, AIMessage

from src.config import settings
from src.agent.tools import ALL_TOOLS

logger = logging.getLogger(__name__)


# ── Event types ────────────────────────────────────────────
# Each SSE event has a "type" and "data":
#   type=thinking    → agent is reasoning
#   type=tool_start  → tool invocation begins (name, input)
#   type=tool_end    → tool invocation complete (name, output_preview)
#   type=answer      → final answer text
#   type=error       → something went wrong
#   type=done        → stream finished


class StreamingCallbackHandler(BaseCallbackHandler):
    """LangChain callback that pushes events to a Queue in real-time."""

    def __init__(self, event_queue: Queue):
        super().__init__()
        self.queue = event_queue
        self._tool_by_run_id = {}

    def _push(self, event_type: str, data: dict):
        self.queue.put({"type": event_type, "data": data})

    def on_llm_new_token(self, token: str, **kwargs: Any) -> Any:
        self._push("token", {"text": token})

    def on_llm_start(self, serialized, prompts, **kwargs):
        self._push("thinking", {"status": "Reasoning about your query..."})

    def on_chat_model_start(self, serialized, messages, **kwargs):
        self._push("thinking", {"status": "Analyzing intent and planning..."})

    def on_tool_start(self, serialized, input_str, *, run_id=None, **kwargs):
        tool_name = serialized.get("name", "unknown")
        if run_id is not None:
            self._tool_by_run_id[str(run_id)] = tool_name
        self._push("tool_start", {
            "tool": tool_name,
            "input": str(input_str)[:200],
        })

    def on_tool_end(self, output, *, run_id=None, **kwargs):
        output_str = str(output)
        tool_name = self._tool_by_run_id.pop(str(run_id), "unknown") if run_id is not None else "unknown"
        self._push("tool_end", {
            "tool": tool_name,
            "output_preview": output_str[:300],
            "output_length": len(output_str),
        })

    def on_agent_action(self, action, **kwargs):
        self._push("decision", {
            "message": action.log[:400] if getattr(action, "log", None) else f"Selecting tool: {action.tool}",
            "tool": action.tool,
        })

    def on_agent_finish(self, finish, **kwargs):
        pass  # We handle final answer separately

    def on_llm_error(self, error, **kwargs):
        self._push("error", {"message": str(error)})

    def on_tool_error(self, error, **kwargs):
        self._push("error", {"message": f"Tool error: {str(error)}"})


SYSTEM_PROMPT = """You are TaarYa, an expert and enthusiastic astronomy assistant.
Your goal is to help users explore the cosmos using real data from Gaia, arXiv, and other sources.

You have access to tools that query real astronomical databases:
1. **cone_search** — Find stars near a sky coordinate (RA/Dec)
2. **star_lookup** — Get details about a specific star by its Gaia source ID
3. **find_nearby_stars** — Find neighbors of a known star
4. **semantic_search** — Search research papers by topic
5. **graph_query** — Explore the knowledge graph for star-paper relationships
6. **count_stars_in_region** — Count stars in a sky area

**Guidelines:**
- **Be Conversational:** Remember previous interactions.
- **Smart Queries:** When users mention coordinates, use cone_search. 
  - If they only give RA, assume Dec=0.
- **Explain Briefly:** Summarize findings clearly.
- **List Results:** If you find 20 or fewer stars, list ALL in markdown table.
- **Tool Use:** Use tools whenever real data is needed.
- **No Results?** Explain why.

Coordinates are in degrees (RA: 0-360, Dec: -90 to +90).
"""


def _get_llm():
    """Create the appropriate LLM."""
    if settings.openai_api_key and settings.openai_api_key != "your-openai-key-here":
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(api_key=settings.openai_api_key, model="gpt-4o-mini", temperature=0, streaming=True)
        except Exception as e:
            logger.warning(f"OpenAI init failed: {e}")

    try:
        from langchain_community.chat_models import ChatOllama
        return ChatOllama(base_url=settings.ollama_base_url, model=settings.ollama_model, temperature=0, streaming=True)
    except ImportError:
        pass

    try:
        from langchain.chat_models import ChatOllama
        return ChatOllama(base_url=settings.ollama_base_url, model=settings.ollama_model, temperature=0, streaming=True)
    except (ImportError, Exception):
        pass

    raise RuntimeError("No LLM available. Set OPENAI_API_KEY or run Ollama.")


def _build_agent(callback_handler):
    """Build a LangChain agent with the streaming callback handler."""
    llm = _get_llm()

    try:
        from langchain.agents import create_tool_calling_agent, AgentExecutor
        from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])

        agent = create_tool_calling_agent(llm, ALL_TOOLS, prompt)
        return AgentExecutor(
            agent=agent,
            tools=ALL_TOOLS,
            verbose=True,
            max_iterations=5,
            handle_parsing_errors=True,
            return_intermediate_steps=True,
            callbacks=[callback_handler],
        )
    except Exception as e:
        logger.warning(f"Tool-calling agent failed: {e}, trying ReAct")

    from langchain.agents import initialize_agent, AgentType
    return initialize_agent(
        tools=ALL_TOOLS,
        llm=llm,
        agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
        verbose=True,
        max_iterations=5,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
        callbacks=[callback_handler],
        agent_kwargs={"prefix": SYSTEM_PROMPT},
    )


def run_agent_streaming(query: str, chat_history: Optional[List[dict]] = None):
    """
    Generator that yields SSE events as the agent processes.
    
    Yields strings in SSE format: "data: {json}\n\n"
    """
    event_queue = Queue()
    callback_handler = StreamingCallbackHandler(event_queue)
    yield f"data: {json.dumps({'type': 'thinking', 'data': {'status': 'Connecting to agent...'}})}\n\n"

    # Convert chat_history
    history_messages = []
    if chat_history:
        for msg in chat_history:
            role = msg.get('role')
            content = msg.get('content', '')
            if role in ('human', 'user'):
                history_messages.append(HumanMessage(content=content))
            elif role in ('ai', 'assistant'):
                history_messages.append(AIMessage(content=content))

    result_holder = {"result": None, "error": None}

    def _run_agent():
        try:
            agent_exec = _build_agent(callback_handler)
            result = agent_exec.invoke({
                "input": query,
                "chat_history": history_messages,
            }, config={"callbacks": [callback_handler]})
            result_holder["result"] = result
        except Exception as e:
            logger.error(f"Stream agent error: {e}")
            result_holder["error"] = str(e)
        finally:
            event_queue.put(None)  # Sentinel: done

    # Run agent in a separate thread so we can yield events
    thread = Thread(target=_run_agent, daemon=True)
    thread.start()

    # Yield events as they arrive
    while True:
        try:
            event = event_queue.get(timeout=0.5)
        except Empty:
            # Heartbeat keeps proxies and browsers flushing the stream.
            yield ": keep-alive\n\n"
            continue

        if event is None:
            break
        yield f"data: {json.dumps(event)}\n\n"

    # Final: yield the answer
    if result_holder["error"]:
        yield f"data: {json.dumps({'type': 'error', 'data': {'message': result_holder['error']}})}\n\n"
    elif result_holder["result"]:
        result = result_holder["result"]
        answer = result.get("output", "I couldn't generate a response.")

        # Extract tool info from intermediate steps
        steps = result.get("intermediate_steps", [])
        tools_used = []
        tool_outputs = []

        for step in steps:
            if hasattr(step[0], 'tool'):
                tool_name = step[0].tool
                tool_input = str(step[0].tool_input)
                tool_output = step[1]

                tools_used.append({
                    "tool": tool_name,
                    "input": tool_input[:200],
                    "output_preview": str(tool_output)[:300],
                })

                if isinstance(tool_output, (list, dict)):
                    tool_outputs.append({"tool": tool_name, "data": tool_output})
                elif isinstance(tool_output, str) and tool_output.strip().startswith('['):
                    try:
                        tool_outputs.append({"tool": tool_name, "data": json.loads(tool_output)})
                    except Exception:
                        pass

        yield f"data: {json.dumps({'type': 'answer', 'data': {'answer': answer, 'tools_used': tools_used, 'tool_outputs': tool_outputs}})}\n\n"

    yield f"data: {json.dumps({'type': 'done', 'data': {}})}\n\n"
