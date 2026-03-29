from contextlib import asynccontextmanager
from inspect import signature
from pathlib import Path
from typing import Any

import pytest
from fastapi import Depends as FastAPIDepends
from fastapi import Request
from starlette.datastructures import Headers

from mountaineer_di import (
    DependenciesBase,
    Depends,
    get_function_dependencies,
    isolate_dependency_only_function,
    strip_depends_from_signature,
)


class Service:
    def __init__(self) -> None:
        self.value = "service"


@pytest.mark.asyncio
async def test_recursive_dependencies_resolve() -> None:
    async def dep_1() -> int:
        return 1

    async def dep_2(dep_1: int = Depends(dep_1)) -> int:
        return dep_1 + 2

    def dep_3(dep_2: int = Depends(dep_2)) -> int:
        return dep_2 + 3

    with pytest.warns(DeprecationWarning):

        class ExampleDependencies(DependenciesBase):
            pass

    ExampleDependencies.dep_1 = dep_1
    ExampleDependencies.dep_2 = dep_2
    ExampleDependencies.dep_3 = dep_3

    async with get_function_dependencies(callable=ExampleDependencies.dep_3) as values:
        assert ExampleDependencies.dep_3(**values) == 6


@pytest.mark.asyncio
async def test_dependency_overrides_apply() -> None:
    def dep_1() -> str:
        return "original"

    def dep_2(dep_1: str = Depends(dep_1)) -> str:
        return f"value:{dep_1}"

    def mocked_dep_1() -> str:
        return "mocked"

    async with get_function_dependencies(
        callable=dep_2,
        dependency_overrides={dep_1: mocked_dep_1},
    ) as values:
        assert dep_2(**values) == "value:mocked"


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

    request = Request(
        {
            "type": "http",
            "path": "/test/5/",
            "query_string": b"url_query_param=test-query-value",
            "headers": Headers({"cookie": "test-cookie=cookie-value"}).raw,
            "method": "GET",
            "scheme": "http",
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
    )

    async with get_function_dependencies(
        callable=render,
        url="/test/{path_param}/",
        request=request,
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

    async def stream(resource: dict[str, Any] = Depends(get_managed_resource)) -> list[int]:
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


def test_incorrect_static_method() -> None:
    with pytest.warns(DeprecationWarning), pytest.raises(TypeError):

        class ExampleIncorrectDependency(DependenciesBase):
            @staticmethod
            async def dep_1() -> int:
                return 1
