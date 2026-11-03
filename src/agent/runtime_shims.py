"""Lightweight fallbacks for LangChain runtime classes used in import-time paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from langchain_core.callbacks import BaseCallbackHandler  # type: ignore
except Exception:  # pragma: no cover - fallback for host-side tests
    class BaseCallbackHandler:  # type: ignore[override]
        """Minimal callback base used when langchain_core is unavailable."""

        pass


try:
    from langchain_core.messages import AIMessage, HumanMessage  # type: ignore
except Exception:  # pragma: no cover - fallback for host-side tests
    @dataclass
    class HumanMessage:  # type: ignore[override]
        content: Any

    @dataclass
    class AIMessage:  # type: ignore[override]
        content: Any
