"""Compatibility helpers for building LangChain agents across API versions."""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)

_STRUCTURED_CHAT_TEMPLATE = """Respond to the user as helpfully as possible.

You can use these tools:
{tools}

When using a tool, respond with exactly one JSON blob:
```json
{{"action": "<tool name or Final Answer>", "action_input": <tool input or final answer>}}
```

Valid "action" values: "Final Answer" or {tool_names}

Use this pattern:
Question: the user request
Thought: your reasoning about next step
Action: one JSON blob
Observation: tool result
... (repeat Thought/Action/Observation as needed)
Thought: I have enough information
Action: one JSON blob with "Final Answer"

Begin.

Question: {input}
Thought:{agent_scratchpad}"""


def _try_initialize_agent(
    *,
    llm: Any,
    tools: Sequence[Any],
    system_prompt: str,
    max_iterations: int,
    max_execution_time: int,
    handle_parsing_errors: bool,
    return_intermediate_steps: bool,
    callbacks: Optional[list[Any]],
) -> Optional[Any]:
    """Try legacy initialize_agent import paths before newer constructor APIs."""

    init_kwargs = {
        "tools": list(tools),
        "llm": llm,
        "verbose": False,
        "max_iterations": max_iterations,
        "max_execution_time": max_execution_time,
        "handle_parsing_errors": handle_parsing_errors,
        "return_intermediate_steps": return_intermediate_steps,
        "agent_kwargs": {"prefix": system_prompt},
    }
    if callbacks:
        init_kwargs["callbacks"] = callbacks

    try:
        from langchain.agents import AgentType, initialize_agent
    except (ImportError, AttributeError) as exc:
        logger.debug("initialize_agent import path #1 unavailable: %s", exc)
    else:
        return initialize_agent(
            agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
            **init_kwargs,
        )

    try:
        from langchain.agents.agent_types import AgentType
        from langchain.agents.initialize import initialize_agent
    except (ImportError, AttributeError) as exc:
        logger.warning(
            "initialize_agent unavailable on this LangChain build; "
            "falling back to create_structured_chat_agent: %s",
            exc,
        )
        return None
    else:
        return initialize_agent(
            agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
            **init_kwargs,
        )


def build_agent_executor(
    *,
    llm: Any,
    tools: Sequence[Any],
    system_prompt: str,
    max_iterations: int,
    max_execution_time: int,
    handle_parsing_errors: bool,
    return_intermediate_steps: bool = True,
    callbacks: Optional[list[Any]] = None,
) -> Any:
    """Build an AgentExecutor compatible with both old and new LangChain APIs."""

    agent = _try_initialize_agent(
        llm=llm,
        tools=tools,
        system_prompt=system_prompt,
        max_iterations=max_iterations,
        max_execution_time=max_execution_time,
        handle_parsing_errors=handle_parsing_errors,
        return_intermediate_steps=return_intermediate_steps,
        callbacks=callbacks,
    )
    if agent is not None:
        return agent

    # Newer LangChain path where initialize_agent is removed.
    from langchain.agents import AgentExecutor, create_structured_chat_agent
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            MessagesPlaceholder("chat_history"),
            ("human", _STRUCTURED_CHAT_TEMPLATE),
        ]
    )

    runnable_agent = create_structured_chat_agent(
        llm=llm,
        tools=list(tools),
        prompt=prompt,
    )
    executor_kwargs = {
        "agent": runnable_agent,
        "tools": list(tools),
        "verbose": False,
        "max_iterations": max_iterations,
        "max_execution_time": max_execution_time,
        "handle_parsing_errors": handle_parsing_errors,
        "return_intermediate_steps": return_intermediate_steps,
    }
    if callbacks:
        executor_kwargs["callbacks"] = callbacks
    return AgentExecutor(**executor_kwargs)
