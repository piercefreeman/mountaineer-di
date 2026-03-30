import asyncio
from contextlib import asynccontextmanager, contextmanager
from inspect import signature
from typing import Annotated, Any, AsyncIterator, Iterator

import pytest

from mountaineer_di import Depend, Depends, provide_dependencies


def test_provide_dependencies_resolves_regular_values() -> None:
    def dependency() -> str:
        return "dependent"

    async def target(value: Annotated[str, Depends(dependency)]) -> str:
        return value

    async def run() -> str:
        async with provide_dependencies(target) as kwargs:
            return await target(**kwargs)

    assert asyncio.run(run()) == "dependent"


def test_provide_dependencies_passes_kwargs_to_dependencies() -> None:
    calls: list[str] = []

    def dependency(prefix: str) -> str:
        calls.append(prefix)
        return f"{prefix}-dep"

    async def target(prefix: str, value: Any = Depend(dependency)) -> str:
        return str(value)

    async def run() -> str:
        async with provide_dependencies(target, {"prefix": "root"}) as kwargs:
            return await target(**kwargs)

    assert asyncio.run(run()) == "root-dep"
    assert calls == ["root"]


def test_provide_dependencies_handles_async_generator_dependency() -> None:
    events: list[str] = []

    async def dependency() -> AsyncIterator[str]:
        events.append("enter")
        try:
            yield "resource"
        finally:
            events.append("exit")

    async def target(resource: Annotated[str, Depend(dependency)]) -> str:
        return resource

    async def run() -> str:
        async with provide_dependencies(target) as kwargs:
            return await target(**kwargs)

    assert asyncio.run(run()) == "resource"
    assert events == ["enter", "exit"]


def test_provide_dependencies_supports_recursive_dependencies() -> None:
    def base() -> str:
        return "base"

    def layer_one(base_value: Annotated[str, Depend(base)]) -> str:
        return f"one-{base_value}"

    async def target(final: Annotated[str, Depend(layer_one)]) -> str:
        return final

    async def run() -> str:
        async with provide_dependencies(target) as kwargs:
            return await target(**kwargs)

    assert asyncio.run(run()) == "one-base"


def test_provide_dependencies_handles_async_function_dependency() -> None:
    async def async_dependency() -> str:
        return "async_value"

    async def target(value: Annotated[str, Depend(async_dependency)]) -> str:
        return value

    async def run() -> str:
        async with provide_dependencies(target) as kwargs:
            return await target(**kwargs)

    assert asyncio.run(run()) == "async_value"


def test_provide_dependencies_handles_sync_generator_dependency() -> None:
    events: list[str] = []

    def sync_dependency() -> Iterator[str]:
        events.append("enter")
        try:
            yield "sync_resource"
        finally:
            events.append("exit")

    async def target(resource: Annotated[str, Depend(sync_dependency)]) -> str:
        return resource

    async def run() -> str:
        async with provide_dependencies(target) as kwargs:
            return await target(**kwargs)

    assert asyncio.run(run()) == "sync_resource"
    assert events == ["enter", "exit"]


def test_provide_dependencies_handles_returned_async_context_manager() -> None:
    events: list[str] = []

    @asynccontextmanager
    async def create_async_resource() -> AsyncIterator[str]:
        events.append("enter")
        try:
            yield "async_cm_resource"
        finally:
            events.append("exit")

    def dependency_returning_async_cm() -> Any:
        return create_async_resource()

    async def target(
        resource: Annotated[str, Depend(dependency_returning_async_cm)],
    ) -> str:
        return resource

    async def run() -> str:
        async with provide_dependencies(target) as kwargs:
            return await target(**kwargs)

    assert asyncio.run(run()) == "async_cm_resource"
    assert events == ["enter", "exit"]


def test_provide_dependencies_handles_returned_sync_context_manager() -> None:
    events: list[str] = []

    @contextmanager
    def create_sync_resource() -> Iterator[str]:
        events.append("enter")
        try:
            yield "sync_cm_resource"
        finally:
            events.append("exit")

    def dependency_returning_sync_cm() -> Any:
        return create_sync_resource()

    async def target(
        resource: Annotated[str, Depend(dependency_returning_sync_cm)],
    ) -> str:
        return resource

    async def run() -> str:
        async with provide_dependencies(target) as kwargs:
            return await target(**kwargs)

    assert asyncio.run(run()) == "sync_cm_resource"
    assert events == ["enter", "exit"]


def test_dependency_cache_is_per_call() -> None:
    calls = 0

    async def counted_dependency() -> str:
        nonlocal calls
        calls += 1
        return "cached"

    async def target(
        first: Annotated[str, Depend(counted_dependency)],
        second: Annotated[str, Depend(counted_dependency)],
    ) -> str:
        return f"{first}:{second}"

    async def run_once() -> str:
        async with provide_dependencies(target) as kwargs:
            return await target(**kwargs)

    assert asyncio.run(run_once()) == "cached:cached"
    assert asyncio.run(run_once()) == "cached:cached"
    assert calls == 2


def test_circular_dependency_detection() -> None:
    async def dep_one(value: str) -> str:
        return value

    async def dep_two(value: Annotated[str, Depend(dep_one)]) -> str:
        return value

    setattr(
        dep_one,
        "__signature__",
        signature(dep_one).replace(
            parameters=[
                signature(dep_one)
                .parameters["value"]
                .replace(
                    default=Depend(dep_two),
                )
            ]
        ),
    )

    async def target(value: Annotated[str, Depend(dep_one)]) -> str:
        return value

    async def run() -> None:
        async with provide_dependencies(target):
            pass

    with pytest.raises(RuntimeError, match="Circular dependency detected"):
        asyncio.run(run())
