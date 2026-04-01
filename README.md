# mountaineer-di

Common dependency injection utilities for Mountaineer and related projects,
with `pydantic` as the only hard dependency.

This package provides a robust set of defining and injecting function dependencies.
It works on its own, and when FastAPI is
installed it can also interoperate with `fastapi.Depends(...)` and
request-bound parameters in the same dependency graph.

## Installation

Install the package with `uv`:

```bash
uv add mountaineer-di
```

## What It Does

`mountaineer-di` lets you declare dependencies on normal Python callables and
resolve them outside a framework request cycle.

It supports:

- Native `Depends(...)` markers
- Nested dependency graphs
- Seeded caller-provided kwargs
- Async and sync dependencies
- Generator and context-manager dependency lifecycles
- FastAPI request/query/path/header/cookie/body extraction when FastAPI is installed
- Runtime dependency overrides
- Callable-level dependency overrides via `@dependency_overrides(...)`

## Quick Start

Use `Depends(...)` to declare dependencies, then call the resolver and invoke
the target with the returned kwargs:

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

The resolver is an async context manager because generator dependencies and
returned context managers stay alive until the `async with` block exits.

## Resolver Entry Points

There are two public ways to resolve a callable:

### `provide_dependencies(...)`

This is the primary entry point:

```python
async with provide_dependencies(
    handler,
    {"prefix": "hi"},
    request=request,
    path="/items/{item_id}",
    dependency_overrides={original_dep: override_dep},
) as kwargs:
    result = await handler(**kwargs)
```

Use it when you want the generic parameter names:

- `func`: target callable
- `kwargs`: seeded values that should already exist in the dependency graph
- `request`: request-like object for request-aware resolution
- `path`: route template used to infer path parameters
- `dependency_overrides`: per-call override mapping

## Native Usage

Seeded kwargs are available to nested dependencies before the handler runs:

```python
from mountaineer_di import Depends, provide_dependencies


def get_message(prefix: str) -> str:
    return f"{prefix} world"


async def handler(prefix: str, message: str = Depends(get_message)) -> str:
    return message


async with provide_dependencies(handler, {"prefix": "seeded"}) as kwargs:
    result = await handler(**kwargs)

print(result)  # seeded world
```

## Request-Bound Resolution

When FastAPI and Starlette are installed, the resolver can populate request
parameters and FastAPI field markers:

```python
from fastapi import Query, Request

from mountaineer_di import Depends, get_function_dependencies


def get_token(request: Request) -> str:
    return request.headers["x-token"]


async def handler(
    item_id: int,
    q: str = Query(),
    token: str = Depends(get_token),
) -> tuple[int, str, str]:
    return (item_id, q, token)


async with get_function_dependencies(
    callable=handler,
    request=request,
    url="/items/{item_id}",
) as kwargs:
    result = await handler(**kwargs)
```

If the request contains `GET /items/7?q=test`, `result` becomes:

```python
(7, "test", "<x-token header>")
```

## FastAPI Interop

You can mix native and FastAPI dependency markers in the same graph:

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


async with get_function_dependencies(
    callable=task,
    request=request,
) as kwargs:
    result = await task(**kwargs)
```

## Dependency Overrides

There are two ways to override dependencies.

### Per-call overrides

Pass a `dependency_overrides` mapping when resolving a callable:

```python
from mountaineer_di import Depends, provide_dependencies


def get_prefix() -> str:
    return "original"


def get_message(prefix: str = Depends(get_prefix)) -> str:
    return f"value:{prefix}"


def mocked_prefix() -> str:
    return "mocked"


async with provide_dependencies(
    get_message,
    dependency_overrides={get_prefix: mocked_prefix},
) as kwargs:
    result = get_message(**kwargs)

print(result)  # value:mocked
```

### Callable-level overrides

Use `@dependency_overrides(...)` when a specific callable should always resolve
with a local override:

```python
from mountaineer_di import Depends, dependency_overrides, provide_dependencies


def require_valid_user() -> str:
    return "request-user"


def get_billing_user_from_request() -> str:
    return "billing-user"


@dependency_overrides({
    require_valid_user: get_billing_user_from_request,
})
async def bill_for_metered_type(
    user: str = Depends(require_valid_user),
) -> str:
    return user


async with provide_dependencies(bill_for_metered_type) as kwargs:
    result = await bill_for_metered_type(**kwargs)

print(result)  # billing-user
```

Callable-level overrides are merged with per-call overrides. If the same
dependency appears in both places, the explicit per-call override wins.

## Development

Development commands are available through the repo `Makefile`, with `lint`,
`ci-lint`, `lint-ruff`, `lint-ty`, and `test` targets following the same
pattern as sibling Mountaineer repositories.
