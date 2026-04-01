from __future__ import annotations

from typing import Any, Callable

DependencyOverrideMap = dict[Callable[..., Any], Callable[..., Any]]

_DEPENDENCY_OVERRIDES_ATTR = "__mountaineer_dependency_overrides__"


def dependency_overrides(
    overrides: DependencyOverrideMap,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Attach default dependency overrides to a callable.

    Parameters:
        overrides: Mapping from original dependency callables to replacement
            callables.

    Metadata:
        runtime_behavior: explicit resolver overrides take precedence
        wrapping_behavior: stores metadata without changing the callable
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        existing = dict(getattr(func, _DEPENDENCY_OVERRIDES_ATTR, {}))
        setattr(func, _DEPENDENCY_OVERRIDES_ATTR, {**existing, **overrides})
        return func

    return decorator


def _callable_dependency_overrides(func: Callable[..., Any]) -> DependencyOverrideMap:
    """Collect dependency override metadata across a ``__wrapped__`` chain."""

    merged: DependencyOverrideMap = {}
    seen_ids: set[int] = set()
    wrapped_chain: list[Callable[..., Any]] = []
    current: Callable[..., Any] | None = func

    while current is not None and id(current) not in seen_ids:
        wrapped_chain.append(current)
        seen_ids.add(id(current))
        current = getattr(current, "__wrapped__", None)

    for target in reversed(wrapped_chain):
        merged.update(getattr(target, _DEPENDENCY_OVERRIDES_ATTR, {}))

    return merged
