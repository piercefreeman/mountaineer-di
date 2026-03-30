# mountaineer-di

Common dependency injection utilities for mountaineer &amp; friends, with pydantic as the only dependency.

This package provides a small dependency resolver built around
`mountaineer_di.Depends(...)`. It works on its own, and when FastAPI is
installed it can also interoperate with `fastapi.Depends(...)` inside the same
dependency graph. You probably won't have to use this library explicitly
but if it's helpful to you then you're certainly welcome to.

## Getting Started

Install the package with `uv`:

```bash
uv add mountaineer-di
```

## Native Usage

Use `Depends(...)` to declare dependencies, then resolve a callable with
`provide_dependencies(...)`:

```python
from typing import Annotated

from mountaineer_di import Depends, provide_dependencies


def get_prefix() -> str:
    return "hello"


def get_message(prefix: str = Depends(get_prefix)) -> str:
    return f"{prefix} world"


async def handler(message: Annotated[str, Depends(get_message)]) -> str:
    return message


async with provide_dependencies(handler) as kwargs:
    result = await handler(**kwargs)
print(result)  # hello world
```

`provide_dependencies(...)` keeps generator and context-manager dependencies
alive for the duration of the async context.

## FastAPI Interop

If you're already using FastAPI elsewhere in your code, you can also use `mountaineer-di` to call into
dependencies that use `fastapi.Depends(...)`:

```python
from fastapi import Depends as FastAPIDepends, Request

from mountaineer_di import Depends, get_function_dependencies


def get_user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


def get_context(
    user_agent: str | None = FastAPIDepends(get_user_agent),
) -> str:
    return user_agent or "unknown"


async def task(context: str = Depends(get_context)) -> str:
    return context
```

For request-bound resolution, pass the request object and route template into
`get_function_dependencies(...)` or `provide_dependencies(...)`.

## Development

Development commands are available through the repo `Makefile`, with `lint`,
`ci-lint`, `lint-ruff`, `lint-ty`, and `test` targets following the same
pattern as sibling Mountaineer repositories.
