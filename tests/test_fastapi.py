from inspect import signature
from typing import Any

import pytest
from fastapi import Depends as FastAPIDepends, Request
from starlette.datastructures import Headers

from mountaineer_di import (
    Depends,
    get_function_dependencies,
    isolate_dependency_only_function,
    strip_depends_from_signature,
)


class Service:
    def __init__(self) -> None:
        self.value = "service"


def _build_request(
    *,
    path: str = "/test/5/",
    query_string: bytes = b"url_query_param=test-query-value",
    cookie_header: str = "test-cookie=cookie-value",
) -> Request:
    return Request(
        {
            "type": "http",
            "path": path,
            "query_string": query_string,
            "headers": Headers({"cookie": cookie_header}).raw,
            "method": "GET",
            "scheme": "http",
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
    )


@pytest.mark.asyncio
async def test_request_path_query_and_dependency_resolution() -> None:
    def cookie_dependency(request: Request) -> str | None:
        return request.cookies.get("test-cookie")

    def render(
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
        callable=render,
        url="/test/{path_param}/",
        request=_build_request(),
    ) as values:
        assert values == {
            "path_param": 5,
            "url_query_param": "test-query-value",
            "cookie_value": "cookie-value",
        }


@pytest.mark.asyncio
async def test_supports_fastapi_depends_import() -> None:
    async def dep() -> str:
        return "resolved"

    async def target(value: str = FastAPIDepends(dep)) -> str:
        return value

    async with get_function_dependencies(callable=target) as values:
        assert await target(**values) == "resolved"


@pytest.mark.asyncio
async def test_parameterless_fastapi_depends_uses_annotation_callable() -> None:
    async def target(service: Service = FastAPIDepends()) -> str:
        return service.value

    async with get_function_dependencies(callable=target) as values:
        assert await target(**values) == "service"


@pytest.mark.asyncio
async def test_native_depends_can_wrap_fastapi_injected_dependency() -> None:
    def cookie_dependency(request: Request) -> str | None:
        return request.cookies.get("test-cookie")

    def native_dependency(
        cookie_value: str | None = FastAPIDepends(cookie_dependency),
    ) -> str:
        return cookie_value or "missing"

    async def target(value: str = Depends(native_dependency)) -> str:
        return value

    async with get_function_dependencies(
        callable=target,
        request=_build_request(cookie_header="test-cookie=interop-cookie"),
    ) as values:
        assert await target(**values) == "interop-cookie"


@pytest.mark.asyncio
async def test_dependency_context_lifetime_covers_streaming_case() -> None:
    cleanup_called = False

    async def get_managed_resource():
        resource = {"alive": True, "values": [1, 2, 3]}
        try:
            yield resource
        finally:
            nonlocal cleanup_called
            resource["alive"] = False
            cleanup_called = True

    async def stream(
        resource: dict[str, Any] = Depends(get_managed_resource),
    ) -> list[int]:
        return list(resource["values"])

    async with get_function_dependencies(callable=stream) as values:
        resource = values["resource"]
        assert resource["alive"]
        assert await stream(**values) == [1, 2, 3]

    assert cleanup_called


def test_isolate_dependency_only_function_and_strip_depends() -> None:
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
