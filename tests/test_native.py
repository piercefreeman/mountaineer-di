import asyncio
import subprocess
import sys
from contextlib import asynccontextmanager, contextmanager
from inspect import signature
from pathlib import Path
from typing import Annotated, Any, AsyncIterator, Iterator

import pytest

from mountaineer_di import Depends, get_function_dependencies, provide_dependencies


def test_depends_is_internal_marker() -> None:
    marker = Depends()

    assert type(marker).__module__.startswith("mountaineer_di")


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

    async def target(prefix: str, value: Any = Depends(dependency)) -> str:
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

    async def target(resource: Annotated[str, Depends(dependency)]) -> str:
        return resource

    async def run() -> str:
        async with provide_dependencies(target) as kwargs:
            return await target(**kwargs)

    assert asyncio.run(run()) == "resource"
    assert events == ["enter", "exit"]


def test_get_function_dependencies_propagates_handler_exception_to_dependency() -> None:
    events: list[str] = []

    async def transactional_dependency() -> AsyncIterator[str]:
        events.append("enter")
        try:
            yield "dependency value"
            events.append("commit")
        except BaseException:
            events.append("rollback")
            raise
        finally:
            events.append("finally")

    async def handler(
        value: str = Depends(transactional_dependency),
    ) -> None:
        raise RuntimeError(f"handler failed after dependency setup: {value}")

    async def run() -> None:
        with pytest.raises(RuntimeError, match="handler failed after dependency setup"):
            async with get_function_dependencies(callable=handler) as kwargs:
                await handler(**kwargs)

    asyncio.run(run())

    assert events == ["enter", "rollback", "finally"]


def test_provide_dependencies_supports_recursive_dependencies() -> None:
    def base() -> str:
        return "base"

    def layer_one(base_value: Annotated[str, Depends(base)]) -> str:
        return f"one-{base_value}"

    async def target(final: Annotated[str, Depends(layer_one)]) -> str:
        return final

    async def run() -> str:
        async with provide_dependencies(target) as kwargs:
            return await target(**kwargs)

    assert asyncio.run(run()) == "one-base"


def test_provide_dependencies_handles_async_function_dependency() -> None:
    async def async_dependency() -> str:
        return "async_value"

    async def target(value: Annotated[str, Depends(async_dependency)]) -> str:
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

    async def target(resource: Annotated[str, Depends(sync_dependency)]) -> str:
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
        resource: Annotated[str, Depends(dependency_returning_async_cm)],
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
        resource: Annotated[str, Depends(dependency_returning_sync_cm)],
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
        first: Annotated[str, Depends(counted_dependency)],
        second: Annotated[str, Depends(counted_dependency)],
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

    async def dep_two(value: Annotated[str, Depends(dep_one)]) -> str:
        return value

    setattr(
        dep_one,
        "__signature__",
        signature(dep_one).replace(
            parameters=[
                signature(dep_one)
                .parameters["value"]
                .replace(
                    default=Depends(dep_two),
                )
            ]
        ),
    )

    async def target(value: Annotated[str, Depends(dep_one)]) -> str:
        return value

    async def run() -> None:
        async with provide_dependencies(target):
            pass

    with pytest.raises(RuntimeError, match="Circular dependency detected"):
        asyncio.run(run())


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


def test_basic_resolution_does_not_require_fastapi_installed() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = """
import asyncio
import builtins
import sys

original_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    blocked_prefixes = ("fastapi", "starlette")
    if any(name == prefix or name.startswith(prefix + ".") for prefix in blocked_prefixes):
        raise ImportError(f"blocked import: {{name}}")
    return original_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import
sys.path.insert(0, {repo_root!r})

from mountaineer_di import Depends, provide_dependencies

def dependency() -> str:
    return "resolved"

async def target(value: str = Depends(dependency)) -> str:
    return value

async def main() -> None:
    async with provide_dependencies(target) as kwargs:
        result = await target(**kwargs)
    assert result == "resolved"
    assert type(Depends()).__module__.startswith("mountaineer_di")

asyncio.run(main())
""".format(repo_root=str(repo_root))

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
