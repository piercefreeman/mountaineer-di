"""FastAPI-adjacent runtime scenarios that are not just signature coverage.

Keep tests here when the behavior under test depends on request-style or
framework-style runtime usage patterns, such as keeping dependency-managed
resources alive across work like streaming.

Do not duplicate generic signature-shape coverage here. FastAPI/native marker
resolution, request-bound parameter injection, and other callable-signature
cases belong in ``test_dependency_signatures.py``.
"""

from typing import Any

import pytest

from mountaineer_di import Depends, get_function_dependencies


@pytest.mark.asyncio
async def test_dependency_context_lifetime_covers_streaming_case() -> None:
    """Verify dependency-managed resources stay open across the work done with resolved kwargs."""

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
