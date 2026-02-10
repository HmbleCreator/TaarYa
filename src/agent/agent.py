"""TaarYa Astronomy Agent — LLM-powered query routing and response generation."""
import logging
import json
from typing import Optional, Dict, Any

from src.config import settings
from src.agent.tools import ALL_TOOLS

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are TaarYa, an intelligent astronomy research assistant.
You have access to tools that query real astronomical databases:

1. **cone_search** — Find stars near a sky coordinate (RA/Dec)
2. **star_lookup** — Get details about a specific star by its Gaia source ID
3. **find_nearby_stars** — Find neighbors of a known star
4. **semantic_search** — Search research papers by topic
5. **graph_query** — Explore the knowledge graph for star-paper relationships
6. **count_stars_in_region** — Count stars in a sky area

Guidelines:
- When users mention coordinates, use cone_search with those coordinates
- When users mention a star ID or source_id, use star_lookup first
- For questions about research or papers, use semantic_search
- Always interpret magnitudes correctly: lower G-mag = brighter star
- Be concise but informative. Include relevant numbers from the data.
- If a tool returns no results, explain why (e.g., collection not populated yet)
- Coordinates are in degrees: RA ranges 0-360, Dec ranges -90 to +90
"""


def _get_llm():
    """Create the appropriate LLM based on configuration."""
    
    # Try OpenAI first if key is configured
    if settings.openai_api_key and settings.openai_api_key != "your-openai-key-here":
        try:
            from langchain_openai import ChatOpenAI
            logger.info("Using OpenAI LLM")
            return ChatOpenAI(
                api_key=settings.openai_api_key,
                model="gpt-4o-mini",
                temperature=0
            )
        except Exception as e:
            logger.warning(f"OpenAI init failed: {e}, falling back to Ollama")
    
    # Try Ollama (local LLM)
    try:
        from langchain_community.chat_models import ChatOllama
        logger.info(f"Using Ollama LLM ({settings.ollama_model})")
        return ChatOllama(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            temperature=0
        )
    except ImportError:
        pass
    
    # Fallback: try older langchain Ollama import
    try:
        from langchain.chat_models import ChatOllama
        logger.info(f"Using Ollama LLM ({settings.ollama_model})")
        return ChatOllama(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            temperature=0
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
    
    def _ensure_agent(self):
        """Lazy-initialize the agent (so server startup isn't slow)."""
        if self._agent is not None:
            return
        
        self._llm = _get_llm()
        
        # Try the modern agent approach first
        try:
            from langchain.agents import create_tool_calling_agent, AgentExecutor
            from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", SYSTEM_PROMPT),
                MessagesPlaceholder(variable_name="chat_history", optional=True),
                ("human", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ])
            
            agent = create_tool_calling_agent(self._llm, ALL_TOOLS, prompt)
            self._agent = AgentExecutor(
                agent=agent,
                tools=ALL_TOOLS,
                verbose=True,
                max_iterations=5,
                handle_parsing_errors=True,
                return_intermediate_steps=True,
            )
            logger.info("Agent initialized (tool-calling mode)")
            return
        except Exception as e:
            logger.warning(f"Tool-calling agent failed: {e}, trying ReAct")
        
        # Fallback: ReAct agent (works with older langchain + ollama)
        try:
            from langchain.agents import initialize_agent, AgentType
            
            self._agent = initialize_agent(
                tools=ALL_TOOLS,
                llm=self._llm,
                agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
                verbose=True,
                max_iterations=5,
                handle_parsing_errors=True,
                return_intermediate_steps=True,
                agent_kwargs={
                    "prefix": SYSTEM_PROMPT,
                }
            )
            logger.info("Agent initialized (ReAct mode)")
        except Exception as e:
            logger.error(f"Failed to initialize agent: {e}")
            raise
    
    def ask(
        self,
        query: str,
        chat_history: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        Process a natural language astronomy query.
        
        Args:
            query: User's question about astronomy
            chat_history: Optional list of previous messages
            
        Returns:
            Dict with 'answer', 'tools_used', and 'steps'
        """
        self._ensure_agent()
        
        try:
            result = self._agent.invoke({
                "input": query,
                "chat_history": chat_history or [],
            })
            
            # Extract tool usage info
            steps = result.get("intermediate_steps", [])
            tools_used = []
            for step in steps:
                if hasattr(step[0], 'tool'):
                    tools_used.append({
                        "tool": step[0].tool,
                        "input": str(step[0].tool_input),
                        "output_preview": str(step[1])[:200],
                    })
            
            return {
                "answer": result.get("output", "I couldn't generate a response."),
                "tools_used": tools_used,
                "query": query,
            }
            
        except Exception as e:
            logger.error(f"Agent error: {e}")
            # Graceful fallback: run tools directly without LLM reasoning
            return self._fallback_response(query)
    
    def _fallback_response(self, query: str) -> Dict[str, Any]:
        """Simple fallback when LLM is unavailable — runs tools based on keywords."""
        query_lower = query.lower()
        tools_used = []
        response_parts = []
        
        # Detect coordinate patterns
        import re
        ra_match = re.search(r'ra\s*[=:]\s*([\d.]+)', query_lower)
        dec_match = re.search(r'dec\s*[=:]\s*([+-]?[\d.]+)', query_lower)
        
        if ra_match and dec_match:
            ra = float(ra_match.group(1))
            dec = float(dec_match.group(1))
            result = ALL_TOOLS[0].invoke({"ra": ra, "dec": dec, "radius_deg": 0.5, "limit": 10})
            tools_used.append({"tool": "cone_search", "input": f"ra={ra}, dec={dec}"})
            response_parts.append(result)
        
        # Detect source_id patterns
        id_match = re.search(r'(?:source_id|star|id)\s*[=:]\s*(\d+)', query_lower)
        if id_match:
            sid = id_match.group(1)
            result = ALL_TOOLS[1].invoke({"source_id": sid})
            tools_used.append({"tool": "star_lookup", "input": sid})
            response_parts.append(result)
        
        # Detect paper/research queries
        if any(w in query_lower for w in ['paper', 'research', 'study', 'published']):
            result = ALL_TOOLS[3].invoke({"query": query, "limit": 5})
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


# Module-level singleton
_agent = None


def ask(query: str, chat_history: Optional[list] = None) -> Dict[str, Any]:
    """Convenience function to ask the TaarYa agent a question."""
    global _agent
    if _agent is None:
        _agent = AstronomyAgent()
    return _agent.ask(query, chat_history)
