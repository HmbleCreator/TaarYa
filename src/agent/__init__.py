"""TaarYa agent package with lazy exports."""

from __future__ import annotations

from typing import Any

__all__ = ["AstronomyAgent", "ask"]


def __getattr__(name: str) -> Any:
    if name in {"AstronomyAgent", "ask"}:
        from src.agent.agent import AstronomyAgent, ask

        return {"AstronomyAgent": AstronomyAgent, "ask": ask}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
