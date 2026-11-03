import sys
from types import ModuleType, SimpleNamespace

from src.agent.langchain_compat import _try_initialize_agent, build_agent_executor


def test_try_initialize_agent_uses_primary_import_path(monkeypatch):
    calls = {}

    def fake_initialize_agent(*, agent, **kwargs):
        calls["agent"] = agent
        calls["kwargs"] = kwargs
        return "primary-agent"

    agents_module = ModuleType("langchain.agents")
    agents_module.AgentType = SimpleNamespace(
        STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION="structured-chat"
    )
    agents_module.initialize_agent = fake_initialize_agent

    monkeypatch.setitem(sys.modules, "langchain", ModuleType("langchain"))
    monkeypatch.setitem(sys.modules, "langchain.agents", agents_module)

    result = _try_initialize_agent(
        llm="llm",
        tools=("tool-a", "tool-b"),
        system_prompt="prompt",
        max_iterations=5,
        max_execution_time=90,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
        callbacks=["cb"],
    )

    assert result == "primary-agent"
    assert calls["agent"] == "structured-chat"
    assert calls["kwargs"]["tools"] == ["tool-a", "tool-b"]
    assert calls["kwargs"]["agent_kwargs"] == {"prefix": "prompt"}
    assert calls["kwargs"]["callbacks"] == ["cb"]


def test_build_agent_executor_falls_back_to_structured_chat_agent(monkeypatch):
    monkeypatch.setattr("src.agent.langchain_compat._try_initialize_agent", lambda **kwargs: None)

    class FakeAgentExecutor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeChatPromptTemplate:
        @classmethod
        def from_messages(cls, messages):
            return {"messages": messages}

    class FakeMessagesPlaceholder:
        def __init__(self, variable_name):
            self.variable_name = variable_name

    def fake_create_structured_chat_agent(*, llm, tools, prompt):
        return {"llm": llm, "tools": tools, "prompt": prompt}

    agents_module = ModuleType("langchain.agents")
    agents_module.AgentExecutor = FakeAgentExecutor
    agents_module.create_structured_chat_agent = fake_create_structured_chat_agent

    prompts_module = ModuleType("langchain_core.prompts")
    prompts_module.ChatPromptTemplate = FakeChatPromptTemplate
    prompts_module.MessagesPlaceholder = FakeMessagesPlaceholder

    monkeypatch.setitem(sys.modules, "langchain", ModuleType("langchain"))
    monkeypatch.setitem(sys.modules, "langchain.agents", agents_module)
    monkeypatch.setitem(sys.modules, "langchain_core", ModuleType("langchain_core"))
    monkeypatch.setitem(sys.modules, "langchain_core.prompts", prompts_module)

    executor = build_agent_executor(
        llm="llm",
        tools=("tool-a",),
        system_prompt="prompt",
        max_iterations=5,
        max_execution_time=90,
        handle_parsing_errors=False,
        return_intermediate_steps=True,
        callbacks=["cb"],
    )

    assert executor.kwargs["tools"] == ["tool-a"]
    assert executor.kwargs["callbacks"] == ["cb"]
    assert executor.kwargs["agent"]["llm"] == "llm"
    assert executor.kwargs["agent"]["tools"] == ["tool-a"]
