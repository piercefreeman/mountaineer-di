from __future__ import annotations

from typing import (
    Any,
    AsyncContextManager,
    AsyncIterator,
    Awaitable,
    Callable,
    ContextManager,
    Iterator,
    TypeVar,
    overload,
)

_T = TypeVar("_T")


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


@overload
def Depends(
    dependency: Callable[
        ...,
        Awaitable[_T]
        | AsyncIterator[_T]
        | Iterator[_T]
        | AsyncContextManager[_T]
        | ContextManager[_T],
    ],
    *,
    use_cache: bool = True,
) -> _T: ...


@overload
def Depends(
    dependency: Callable[..., _T],
    *,
    use_cache: bool = True,
) -> _T: ...


@overload
def Depends(
    *,
    use_cache: bool = True,
) -> Any: ...


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
