from __future__ import annotations

import functools
from inspect import signature
from typing import Annotated, Any

import pytest
from fastapi import Depends as FastAPIDepends, Query, Request
from starlette.datastructures import Headers

from mountaineer_di import (
    Depends,
    get_function_dependencies,
    isolate_dependency_only_function,
    provide_dependencies,
    strip_depends_from_signature,
)

pytestmark = pytest.mark.asyncio


def _annotated_dependency_value() -> str:
    return "annotated-value"


def _partial_prefix() -> str:
    return "partial"


def _annotated_partial_dependency(
    value: Annotated[str, Depends(_partial_prefix)],
    *,
    suffix: str,
) -> str:
    return f"{value}-{suffix}"


def _constructor_prefix() -> str:
    return "constructor"


class _ConstructedService:
    def __init__(self, value: Annotated[str, Depends(_constructor_prefix)]) -> None:
        self.value = value


class _FastAPIConstructedService:
    def __init__(self) -> None:
        self.value = "fastapi-service"


def _build_request(
    *,
    path: str = "/items/5/",
    query_string: bytes = b"q=test-query",
    cookie_header: str = "test-cookie=cookie-value",
) -> Request:
    return Request(
        {
            "type": "http",
            "path": path,
            "query_string": query_string,
            "headers": Headers(
                {
                    "cookie": cookie_header,
                    "x-token": "edge-token",
                }
            ).raw,
            "method": "GET",
            "scheme": "http",
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
    )


async def test_sync_function_dependency_returns_plain_value() -> None:
    """Verify a plain sync dependency resolves into a simple handler signature."""

    def dependency() -> str:
        return "dependent"

    async def handler(value: str = Depends(dependency)) -> str:
        return value

    async with provide_dependencies(handler) as kwargs:
        assert await handler(**kwargs) == "dependent"


async def test_async_function_dependency_returns_plain_value() -> None:
    """Verify an async dependency resolves into the handler without extra lifecycle behavior."""

    async def dependency() -> str:
        return "async-value"

    async def handler(value: str = Depends(dependency)) -> str:
        return value

    async with provide_dependencies(handler) as kwargs:
        assert await handler(**kwargs) == "async-value"


async def test_dependency_can_read_seeded_kwargs() -> None:
    """Verify seeded kwargs are available to dependency signatures before handler invocation."""

    calls: list[str] = []

    def dependency(prefix: str) -> str:
        calls.append(prefix)
        return f"{prefix}-dep"

    async def handler(prefix: str, value: Any = Depends(dependency)) -> str:
        return str(value)

    async with provide_dependencies(handler, {"prefix": "root"}) as kwargs:
        assert await handler(**kwargs) == "root-dep"

    assert calls == ["root"]


async def test_recursive_dependencies_resolve_in_order() -> None:
    """Verify nested dependency signatures resolve transitively across multiple layers."""

    def base() -> str:
        return "base"

    def layer_one(base_value: str = Depends(base)) -> str:
        return f"one-{base_value}"

    async def handler(final: str = Depends(layer_one)) -> str:
        return final

    async with provide_dependencies(handler) as kwargs:
        assert await handler(**kwargs) == "one-base"


async def test_bound_method_dependency_is_supported() -> None:
    """Verify bound methods are treated as callable dependencies with the expected signature."""

    class Service:
        def dependency(self) -> str:
            return "method-value"

    service = Service()

    async def handler(value: str = Depends(service.dependency)) -> str:
        return value

    async with provide_dependencies(handler) as kwargs:
        assert await handler(**kwargs) == "method-value"


async def test_annotated_function_dependency_is_supported() -> None:
    """Verify Annotated dependency markers are discovered from the handler parameter annotation."""

    async def handler(
        value: Annotated[str, Depends(_annotated_dependency_value)],
    ) -> str:
        return value

    async with provide_dependencies(handler) as kwargs:
        assert await handler(**kwargs) == "annotated-value"


async def test_wrapped_function_preserves_annotated_dependency_resolution() -> None:
    """Verify decorator-wrapped callables still resolve Annotated markers through __wrapped__."""

    async def original(
        value: Annotated[str, Depends(_annotated_dependency_value)],
    ) -> str:
        return value

    @functools.wraps(original)
    async def wrapped(*args: Any, **kwargs: Any) -> str:
        return await original(*args, **kwargs)

    async with provide_dependencies(wrapped) as kwargs:
        assert await wrapped(**kwargs) == "annotated-value"


async def test_partial_dependency_preserves_default_markers() -> None:
    """Verify functools.partial keeps default-value Depends markers on the wrapped dependency."""

    def prefix() -> str:
        return "partial"

    def dependency(value: str = Depends(prefix), *, suffix: str) -> str:
        return f"{value}-{suffix}"

    partial_dependency = functools.partial(dependency, suffix="default")

    async def handler(value: str = Depends(partial_dependency)) -> str:
        return value

    async with provide_dependencies(handler) as kwargs:
        assert await handler(**kwargs) == "partial-default"


async def test_partial_dependency_preserves_annotated_markers() -> None:
    """Verify functools.partial also preserves annotation-only dependency markers on the wrapped callable."""

    partial_dependency = functools.partial(
        _annotated_partial_dependency,
        suffix="annotated",
    )

    async def handler(value: str = Depends(partial_dependency)) -> str:
        return value

    async with provide_dependencies(handler) as kwargs:
        assert await handler(**kwargs) == "partial-annotated"


async def test_callable_instance_supports_default_markers() -> None:
    """Verify callable instances resolve default-value Depends markers from their __call__ signature."""

    def prefix() -> str:
        return "instance"

    class Service:
        def __call__(self, value: str = Depends(prefix)) -> str:
            return f"{value}-default"

    async def handler(value: str = Depends(Service())) -> str:
        return value

    async with provide_dependencies(handler) as kwargs:
        assert await handler(**kwargs) == "instance-default"


async def test_callable_instance_supports_annotated_and_request_injection() -> None:
    """Verify callable instances resolve postponed annotations for both request and query-bound parameters."""

    class Service:
        def __call__(
            self,
            request: Request,
            value: Annotated[str, Query()],
        ) -> str:
            return f"{request.headers['x-token']}:{value}"

    async def handler(value: str = Depends(Service())) -> str:
        return value

    async with get_function_dependencies(
        callable=handler,
        request=_build_request(query_string=b"value=callable-query"),
    ) as kwargs:
        assert await handler(**kwargs) == "edge-token:callable-query"


async def test_parameterless_depends_uses_annotated_constructor_dependencies() -> None:
    """Verify parameterless Depends() can instantiate classes whose constructor uses Annotated dependencies."""

    async def handler(service: _ConstructedService = Depends()) -> str:
        return service.value

    async with provide_dependencies(handler) as kwargs:
        assert await handler(**kwargs) == "constructor"


async def test_fastapi_depends_import_is_supported() -> None:
    """Verify fastapi.Depends markers resolve in the same signature walker as native markers."""

    async def dependency() -> str:
        return "resolved"

    async def handler(value: str = FastAPIDepends(dependency)) -> str:
        return value

    async with get_function_dependencies(callable=handler) as kwargs:
        assert await handler(**kwargs) == "resolved"


async def test_parameterless_fastapi_depends_uses_annotation_callable() -> None:
    """Verify parameterless fastapi.Depends() can instantiate the annotated class dependency."""

    async def handler(service: _FastAPIConstructedService = FastAPIDepends()) -> str:
        return service.value

    async with get_function_dependencies(callable=handler) as kwargs:
        assert await handler(**kwargs) == "fastapi-service"


async def test_native_depends_can_wrap_fastapi_injected_dependency() -> None:
    """Verify native dependency signatures can nest FastAPI dependency markers inside the same graph."""

    def cookie_dependency(request: Request) -> str | None:
        return request.cookies.get("test-cookie")

    def native_dependency(
        cookie_value: str | None = FastAPIDepends(cookie_dependency),
    ) -> str:
        return cookie_value or "missing"

    async def handler(value: str = Depends(native_dependency)) -> str:
        return value

    async with get_function_dependencies(
        callable=handler,
        request=_build_request(cookie_header="test-cookie=interop-cookie"),
    ) as kwargs:
        assert await handler(**kwargs) == "interop-cookie"


async def test_request_path_query_and_dependency_resolution() -> None:
    """Verify request-aware path, inferred query, and request-backed dependency parameters resolve together."""

    def cookie_dependency(request: Request) -> str | None:
        return request.cookies.get("test-cookie")

    def handler(
        path_param: int,
        url_query_param: str | None = None,
        cookie_value: str | None = Depends(cookie_dependency),
    ) -> dict[str, Any]:
        return {
            "path_param": path_param,
            "url_query_param": url_query_param,
            "cookie_value": cookie_value,
        }

    async with get_function_dependencies(
        callable=handler,
        url="/test/{path_param}/",
        request=_build_request(
            path="/test/5/",
            query_string=b"url_query_param=test-query-value",
        ),
    ) as kwargs:
        assert handler(**kwargs) == {
            "path_param": 5,
            "url_query_param": "test-query-value",
            "cookie_value": "cookie-value",
        }


async def test_request_path_query_and_native_dependency_markers_work_together() -> None:
    """Verify explicit Query fields and native Depends markers resolve together in a request-bound signature."""

    def dependency(request: Request) -> str:
        return request.headers["x-token"]

    async def handler(
        item_id: int,
        q: str = Query(),
        token: str = Depends(dependency),
    ) -> tuple[int, str, str]:
        return (item_id, q, token)

    async with get_function_dependencies(
        callable=handler,
        request=_build_request(path="/items/7/", query_string=b"q=request-query"),
        url="/items/{item_id}/",
    ) as kwargs:
        assert await handler(**kwargs) == (7, "request-query", "edge-token")


async def test_positional_only_parameters_raise_a_clear_error() -> None:
    """Verify unsupported positional-only parameters fail before returning unusable kwargs."""

    async def handler(value: str, /) -> str:
        return value

    with pytest.raises(TypeError, match="Positional-only parameter 'value'"):
        async with provide_dependencies(handler, {"value": "x"}):
            pytest.fail("positional-only callables should fail before yielding kwargs")


async def test_isolate_dependency_only_function_and_strip_depends() -> None:
    """Verify the signature helper utilities separate dependency parameters from user-supplied ones."""

    def test_dependency() -> int:
        return 1

    def test_complex_function(
        payload: dict[str, Any],
        request: Request,
        resolved_dep: int = Depends(test_dependency),
        annotated_dep: int = FastAPIDepends(test_dependency),
    ) -> int:
        return resolved_dep + annotated_dep

    modified = isolate_dependency_only_function(test_complex_function)
    assert set(signature(modified).parameters) == {"resolved_dep", "annotated_dep"}

    stripped = strip_depends_from_signature(test_complex_function)
    assert set(stripped.parameters) == {"payload", "request"}
