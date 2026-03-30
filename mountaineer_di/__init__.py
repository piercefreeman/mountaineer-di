from __future__ import annotations

from .fastapi_compat import (
    fetch_recent_stable_fastapi_versions as fetch_recent_stable_fastapi_versions,
)

_RESOLVER_EXPORTS = {
    "Depend",
    "DependenciesBase",
    "DependencyResolver",
    "Depends",
    "get_function_dependencies",
    "isolate_dependency_only_function",
    "provide_dependencies",
    "strip_depends_from_signature",
}

__all__ = [
    "Depend",
    "DependenciesBase",
    "DependencyResolver",
    "Depends",
    "fetch_recent_stable_fastapi_versions",
    "get_function_dependencies",
    "isolate_dependency_only_function",
    "provide_dependencies",
    "strip_depends_from_signature",
]


def __getattr__(name: str):
    if name in _RESOLVER_EXPORTS:
        from . import resolver

        value = getattr(resolver, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
