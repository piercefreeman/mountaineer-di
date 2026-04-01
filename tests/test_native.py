"""Runtime behavior for the native dependency resolver.

Keep tests here when the main question is how the resolver behaves after a
dependency has been selected: generator and context-manager lifecycle,
exception propagation during teardown, LIFO unwinding, unmanaged return values,
cache behavior, circular detection, overrides, and native operation without
FastAPI installed.

Do not put callable-shape or parameter-signature coverage here. Tests whose
main purpose is "can this kind of function signature be injected correctly?"
belong in ``test_dependency_signatures.py`` instead.
"""

import asyncio
import functools
import subprocess
import sys
from contextlib import asynccontextmanager, contextmanager
from inspect import signature
from pathlib import Path
from typing import Annotated, Any, AsyncIterator, Iterator

import pytest

from mountaineer_di import (
    Depends,
    dependency_override,
    get_function_dependencies,
    provide_dependencies,
)


def test_depends_is_internal_marker() -> None:
    """Verify the public marker comes from this package even when FastAPI is installed."""

    marker = Depends()

    assert type(marker).__module__.startswith("mountaineer_di")


def test_provide_dependencies_handles_async_generator_dependency() -> None:
    """Verify async generator dependencies stay open through the handler call and then clean up."""

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


def test_provide_dependencies_handles_sync_generator_dependency() -> None:
    """Verify sync generator dependencies follow the same enter and exit lifecycle as async ones."""

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


def test_get_function_dependencies_propagates_handler_exception_to_dependency() -> None:
    """Verify handler exceptions are thrown back into async generator dependencies during teardown."""

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

    async def handler(value: str = Depends(transactional_dependency)) -> None:
        raise RuntimeError(f"handler failed after dependency setup: {value}")

    async def run() -> None:
        with pytest.raises(RuntimeError, match="handler failed after dependency setup"):
            async with get_function_dependencies(callable=handler) as kwargs:
                await handler(**kwargs)

    asyncio.run(run())

    assert events == ["enter", "rollback", "finally"]


def test_sync_generator_dependency_receives_handler_exception() -> None:
    """Verify sync generator dependencies also receive handler exceptions for rollback-style cleanup."""

    events: list[str] = []

    def dependency() -> Iterator[str]:
        events.append("enter")
        try:
            yield "resource"
            events.append("commit")
        except BaseException:
            events.append("rollback")
            raise
        finally:
            events.append("finally")

    async def handler(value: str = Depends(dependency)) -> None:
        raise RuntimeError(f"boom:{value}")

    async def run() -> None:
        with pytest.raises(RuntimeError, match="boom:resource"):
            async with provide_dependencies(handler) as kwargs:
                await handler(**kwargs)

    asyncio.run(run())

    assert events == ["enter", "rollback", "finally"]


def test_provide_dependencies_handles_returned_async_context_manager() -> None:
    """Verify a dependency that returns an async context manager is entered and exited automatically."""

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
    """Verify a dependency that returns a sync context manager is entered and exited automatically."""

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


def test_awaited_dependency_returning_async_context_manager_is_managed() -> None:
    """Verify async dependencies can await to a context manager and still be managed by the resolver."""

    events: list[str] = []

    @asynccontextmanager
    async def resource() -> AsyncIterator[str]:
        events.append("enter")
        try:
            yield "awaited-cm"
        finally:
            events.append("exit")

    async def dependency() -> Any:
        return resource()

    async def handler(value: str = Depends(dependency)) -> str:
        return value

    async def run() -> str:
        async with provide_dependencies(handler) as kwargs:
            return await handler(**kwargs)

    assert asyncio.run(run()) == "awaited-cm"
    assert events == ["enter", "exit"]


def test_dependency_setup_failure_propagates_into_open_dependencies() -> None:
    """Verify dependencies opened during setup see a later setup failure during teardown."""

    events: list[str] = []

    async def first_dependency() -> AsyncIterator[str]:
        events.append("enter")
        try:
            yield "resource"
            events.append("commit")
        except BaseException:
            events.append("rollback")
            raise
        finally:
            events.append("finally")

    def second_dependency(_: str = Depends(first_dependency)) -> str:
        raise RuntimeError("setup failed")

    async def handler(value: str = Depends(second_dependency)) -> str:
        return value

    async def run() -> None:
        with pytest.raises(RuntimeError, match="setup failed"):
            async with provide_dependencies(handler):
                pytest.fail(
                    "dependency setup should fail before yielding handler kwargs"
                )

    asyncio.run(run())

    assert events == ["enter", "rollback", "finally"]


def test_sync_context_manager_dependency_can_suppress_handler_exception() -> None:
    """Verify sync context manager dependencies can suppress handler exceptions via __exit__."""

    events: list[str] = []

    @contextmanager
    def dependency() -> Iterator[str]:
        events.append("enter")
        try:
            yield "resource"
        except RuntimeError:
            events.append("suppressed")
        finally:
            events.append("finally")

    async def handler(value: str = Depends(dependency)) -> None:
        raise RuntimeError(f"boom:{value}")

    async def run() -> None:
        async with provide_dependencies(handler) as kwargs:
            await handler(**kwargs)

    asyncio.run(run())

    assert events == ["enter", "suppressed", "finally"]


def test_async_context_manager_dependency_can_suppress_handler_exception() -> None:
    """Verify async context manager dependencies can suppress handler exceptions via __aexit__."""

    events: list[str] = []

    @asynccontextmanager
    async def dependency() -> AsyncIterator[str]:
        events.append("enter")
        try:
            yield "resource"
        except RuntimeError:
            events.append("suppressed")
        finally:
            events.append("finally")

    async def handler(value: str = Depends(dependency)) -> None:
        raise RuntimeError(f"boom:{value}")

    async def run() -> None:
        async with provide_dependencies(handler) as kwargs:
            await handler(**kwargs)

    asyncio.run(run())

    assert events == ["enter", "suppressed", "finally"]


def test_nested_context_managers_exit_in_lifo_order() -> None:
    """Verify dependency teardown unwinds nested managed resources in LIFO order."""

    events: list[str] = []

    @contextmanager
    def first() -> Iterator[str]:
        events.append("first-enter")
        try:
            yield "first"
        finally:
            events.append("first-exit")

    @asynccontextmanager
    async def second(_: str = Depends(first)) -> AsyncIterator[str]:
        events.append("second-enter")
        try:
            yield "second"
        finally:
            events.append("second-exit")

    async def handler(_: str = Depends(second)) -> None:
        events.append("handler")

    async def run() -> None:
        async with provide_dependencies(handler) as kwargs:
            await handler(**kwargs)

    asyncio.run(run())

    assert events == [
        "first-enter",
        "second-enter",
        "handler",
        "second-exit",
        "first-exit",
    ]


def test_close_only_return_values_are_not_auto_managed() -> None:
    """Verify plain return values with close methods are not treated as managed context lifecycles."""

    class Resource:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    resource = Resource()

    def dependency() -> Resource:
        return resource

    async def handler(value: Resource = Depends(dependency)) -> Resource:
        return value

    async def run() -> Resource:
        async with provide_dependencies(handler) as kwargs:
            return await handler(**kwargs)

    assert asyncio.run(run()) is resource
    assert resource.closed is False


def test_dependency_cache_is_per_call() -> None:
    """Verify use_cache scopes dependency values to a single resolver instance."""

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
    """Verify the resolver detects circular dependency graphs before recursing forever."""

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
    """Verify dependency overrides swap implementations throughout the resolved graph."""

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
async def test_callable_dependency_overrides_decorator_applies() -> None:
    """Verify ``@dependency_override(...)`` supplies a default override for a callable."""

    def dep_1() -> str:
        return "original"

    def mocked_dep_1() -> str:
        return "decorated"

    @dependency_override(dep_1, mocked_dep_1)
    async def handler(value: str = Depends(dep_1)) -> str:
        return value

    async with provide_dependencies(handler) as kwargs:
        assert await handler(**kwargs) == "decorated"


@pytest.mark.asyncio
async def test_callable_dependency_overrides_follow_wrapped_callables() -> None:
    """Verify callable-level overrides survive wrapper decorators that preserve ``__wrapped__``."""

    def dep_1() -> str:
        return "original"

    def mocked_dep_1() -> str:
        return "wrapped"

    @dependency_override(dep_1, mocked_dep_1)
    async def original(value: str = Depends(dep_1)) -> str:
        return value

    @functools.wraps(original)
    async def wrapped(*args: Any, **kwargs: Any) -> str:
        return await original(*args, **kwargs)

    async with provide_dependencies(wrapped) as values:
        assert await wrapped(**values) == "wrapped"


@pytest.mark.asyncio
async def test_runtime_dependency_overrides_take_precedence_over_callable_defaults() -> (
    None
):
    """Verify explicit resolver overrides merge with and override callable-level defaults."""

    def dep_1() -> str:
        return "one"

    def dep_2() -> str:
        return "two"

    def decorated_dep_1() -> str:
        return "decorated-one"

    def decorated_dep_2() -> str:
        return "decorated-two"

    def runtime_dep_2() -> str:
        return "runtime-two"

    @dependency_override(dep_1, decorated_dep_1)
    @dependency_override(dep_2, decorated_dep_2)
    async def handler(
        first: str = Depends(dep_1),
        second: str = Depends(dep_2),
    ) -> tuple[str, str]:
        return (first, second)

    async with provide_dependencies(
        handler,
        dependency_overrides={dep_2: runtime_dep_2},
    ) as kwargs:
        assert await handler(**kwargs) == ("decorated-one", "runtime-two")


def test_basic_resolution_does_not_require_fastapi_installed() -> None:
    """Verify native dependency resolution works when FastAPI and Starlette imports are unavailable."""

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
