from __future__ import annotations

from typing import Any, Callable


class _DependsMarker:
    """
    Internal dependency marker backing :func:`Depends`.

    Parameters:
        dependency: Callable to resolve for this parameter. If omitted, the
            resolver will fall back to the parameter annotation when possible.
        use_cache: Whether this dependency should be cached for the lifetime of
            a single resolver instance.

    Metadata:
        constructor: created via ``mountaineer_di.Depends(...)``
        runtime_dependency: none on FastAPI
    """

    def __init__(
        self,
        dependency: Callable[..., Any] | None = None,
        *,
        use_cache: bool = True,
    ) -> None:
        self.dependency = dependency
        self.use_cache = use_cache

    def __repr__(self) -> str:
        dependency_name = getattr(self.dependency, "__name__", self.dependency)
        return (
            f"{self.__class__.__name__}("
            f"dependency={dependency_name!r}, use_cache={self.use_cache!r})"
        )


def Depends(
    dependency: Callable[..., Any] | None = None,
    *,
    use_cache: bool = True,
) -> Any:
    """
    Create a dependency marker using FastAPI-style call syntax.

    Parameters:
        dependency: Callable to resolve for this parameter. If omitted, the
            resolver will fall back to the parameter annotation when possible.
        use_cache: Whether this dependency should be cached for the lifetime of
            a single resolver instance.

    Metadata:
        compatibility: mirrors the common FastAPI ``Depends(...)`` call shape
        runtime_dependency: none on FastAPI
    """

    return _DependsMarker(dependency=dependency, use_cache=use_cache)
