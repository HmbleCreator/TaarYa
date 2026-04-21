"""Retrieval module for hybrid search.

Import heavy backends lazily so lightweight modules can be imported
without requiring every database client to be available up front.
"""

from importlib import import_module
from typing import Any

__all__ = [
    "SpatialSearch",
    "VectorSearch",
    "GraphSearch",
    "HybridSearch",
    "SearchType",
]

_MODULE_ATTRS = {
    "SpatialSearch": ("src.retrieval.spatial_search", "SpatialSearch"),
    "VectorSearch": ("src.retrieval.vector_search", "VectorSearch"),
    "GraphSearch": ("src.retrieval.graph_search", "GraphSearch"),
    "HybridSearch": ("src.retrieval.hybrid_search", "HybridSearch"),
    "SearchType": ("src.retrieval.hybrid_search", "SearchType"),
}


def __getattr__(name: str) -> Any:
    """Resolve retrieval symbols lazily on first access."""
    if name not in _MODULE_ATTRS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _MODULE_ATTRS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy attributes in interactive tooling."""
    return sorted(set(globals()) | set(__all__))
