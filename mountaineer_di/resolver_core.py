from __future__ import annotations

import inspect
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from inspect import Parameter, Signature, signature
from types import TracebackType
from typing import Any, AsyncIterator, Callable, Optional

from .annotations import (
    _MISSING,
    _callable_from_annotation,
    _coerce_value,
    _dependency_marker,
    _field_default,
    _field_info,
    _get_parameter_hints,
    _is_request_annotation,
    _pick_query_value,
    _strip_annotated,
)
from .optional_fastapi import _fastapi_field_info_kind
from .request_parsing import _RequestResolver, _ResolvedParameter


class DependencyResolver:
    """
    Resolve FastAPI-style dependencies outside the framework request cycle.

    Parameters:
        initial_kwargs: Explicit values that should be available to the target
            callable and any nested dependencies.
        request: Optional request-like object used to resolve request parameters plus
            query, path, header, cookie, and body values.
        path: Optional route template such as ``"/items/{item_id}"`` used to
            infer path parameters when ``request.scope["path_params"]`` is not
            already populated.
        dependency_overrides: Optional mapping of original dependency callables
            to replacement callables, mirroring FastAPI's testing override
            pattern.

    Metadata:
        cache_scope: per-resolver instance when ``Depends(..., use_cache=True)``
        cleanup: sync and async generator dependencies stay alive until
            :meth:`close` runs
        compatibility: supports both ``mountaineer_di.Depends`` and
            ``fastapi.Depends`` markers
    """

    def __init__(
        self,
        initial_kwargs: Optional[dict[str, Any]] = None,
        *,
        request: Any | None = None,
        path: str | None = None,
        dependency_overrides: dict[Callable[..., Any], Callable[..., Any]]
        | None = None,
    ) -> None:
        self._context: dict[str, Any] = dict(initial_kwargs or {})
        self._cache: dict[Callable[..., Any], Any] = {}
        self._active: set[Callable[..., Any]] = set()
        self._stack = AsyncExitStack()
        self._request = request
        self._request_resolver = _RequestResolver(request=request, path_template=path)
        self._dependency_overrides = dependency_overrides or {}

        if request is not None:
            self._context.setdefault("request", request)

    async def close(self) -> None:
        """Release any dependency contexts opened during resolution."""

        await self._stack.aclose()

    async def exit(
        self,
        exc_type: type[BaseException] | None = None,
        exc: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> bool:
        """Release dependency contexts with optional exception details."""

        return bool(await self._stack.__aexit__(exc_type, exc, traceback))

    async def build_call_kwargs(self, func: Callable[..., Any]) -> dict[str, Any]:
        """
        Build the keyword arguments required to call ``func``.

        Parameters:
            func: Callable whose dependency-marked parameters should be
                resolved.

        Returns:
            A mapping ready to be expanded as ``func(**kwargs)``.

        Raises:
            TypeError: If a required non-dependency parameter cannot be
                resolved.
            RuntimeError: If dependency resolution detects a cycle.
        """

        func_signature = signature(func)
        hints = _get_parameter_hints(func)

        await self._seed_non_dependency_context(func_signature, hints)

        call_kwargs: dict[str, Any] = {}
        func_name = getattr(func, "__name__", func.__class__.__name__)
        for name, parameter in func_signature.parameters.items():
            if parameter.kind in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD):
                continue
            if parameter.kind is Parameter.POSITIONAL_ONLY:
                raise TypeError(
                    f"Positional-only parameter '{name}' for {func_name} is not "
                    "supported because dependency resolution passes values by keyword"
                )

            if name in self._context:
                call_kwargs[name] = self._context[name]
                continue

            annotation = hints.get(name, parameter.annotation)
            marker = _dependency_marker(parameter, annotation)
            if marker is not None:
                value = await self._resolve_dependency(
                    marker=marker,
                    parameter=parameter,
                    annotation=annotation,
                )
                self._context[name] = value
                call_kwargs[name] = value
                continue

            raise TypeError(f"Missing required parameter '{name}' for {func_name}")

        return call_kwargs

    async def _seed_non_dependency_context(
        self,
        func_signature: Signature,
        hints: dict[str, Any],
    ) -> None:
        for name, parameter in func_signature.parameters.items():
            if parameter.kind in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD):
                continue
            if name in self._context:
                continue

            annotation = hints.get(name, parameter.annotation)
            if _dependency_marker(parameter, annotation) is not None:
                continue

            resolved = await self._resolve_non_dependency_parameter(
                parameter=parameter,
                annotation=annotation,
            )
            if resolved.found:
                self._context[name] = resolved.value

    async def _resolve_dependency(
        self,
        *,
        marker: Any,
        parameter: inspect.Parameter,
        annotation: Any,
    ) -> Any:
        dependency = marker.dependency or _callable_from_annotation(annotation)
        if dependency is None:
            raise TypeError(
                f"Depends requires a dependency callable for parameter '{parameter.name}'"
            )

        cache_key = dependency
        if marker.use_cache and cache_key in self._cache:
            return self._cache[cache_key]
        if cache_key in self._active:
            name = getattr(cache_key, "__name__", cache_key.__class__.__name__)
            raise RuntimeError(f"Circular dependency detected for {name}")

        resolved_dependency = self._dependency_overrides.get(dependency, dependency)
        self._active.add(cache_key)
        try:
            kwargs = await self.build_call_kwargs(resolved_dependency)
            value = await self._call_dependency(resolved_dependency, kwargs)
            if marker.use_cache:
                self._cache[cache_key] = value
            return value
        finally:
            self._active.discard(cache_key)

    async def _call_dependency(
        self,
        dependency: Callable[..., Any],
        kwargs: dict[str, Any],
    ) -> Any:
        if inspect.isasyncgenfunction(dependency):
            context_manager = asynccontextmanager(dependency)(**kwargs)
            return await self._stack.enter_async_context(context_manager)
        if inspect.isgeneratorfunction(dependency):
            context_manager = contextmanager(dependency)(**kwargs)
            return self._stack.enter_context(context_manager)

        result = dependency(**kwargs)
        if inspect.isawaitable(result):
            result = await result

        if hasattr(result, "__aenter__") and hasattr(result, "__aexit__"):
            return await self._stack.enter_async_context(result)  # type: ignore[arg-type]
        if hasattr(result, "__enter__") and hasattr(result, "__exit__"):
            return self._stack.enter_context(result)  # type: ignore[arg-type]
        return result

    async def _resolve_non_dependency_parameter(
        self,
        *,
        parameter: inspect.Parameter,
        annotation: Any,
    ) -> _ResolvedParameter:
        plain_annotation = _strip_annotated(annotation)
        if _is_request_annotation(plain_annotation):
            if self._request is None:
                return _ResolvedParameter(found=False)
            return _ResolvedParameter(found=True, value=self._request)

        field_info = _field_info(parameter, annotation)
        if field_info is not None:
            resolved = await self._resolve_from_field_info(
                parameter,
                annotation,
                field_info,
            )
            if resolved.found:
                return resolved
            default = _field_default(field_info)
            if default is not _MISSING:
                return _ResolvedParameter(found=True, value=default)
        else:
            resolved = await self._resolve_from_inferred_request(parameter, annotation)
            if resolved.found:
                return resolved

        if parameter.default is not inspect.Parameter.empty:
            return _ResolvedParameter(found=True, value=parameter.default)
        return _ResolvedParameter(found=False)

    async def _resolve_from_field_info(
        self,
        parameter: inspect.Parameter,
        annotation: Any,
        field_info: Any,
    ) -> _ResolvedParameter:
        alias = getattr(field_info, "alias", None) or parameter.name
        field_kind = _fastapi_field_info_kind(field_info)
        if field_kind == "path":
            raw_value = self._request_resolver.path_params().get(alias)
            return self._coerce_optional(annotation, raw_value)
        if field_kind == "query":
            raw_value = _pick_query_value(
                self._request_resolver.query_values(alias),
                annotation,
            )
            return self._coerce_optional(annotation, raw_value)
        if field_kind == "header":
            header_name = alias
            if header_name == parameter.name and getattr(
                field_info,
                "convert_underscores",
                True,
            ):
                header_name = header_name.replace("_", "-")
            raw_value = self._request_resolver.header_value(header_name)
            return self._coerce_optional(annotation, raw_value)
        if field_kind == "cookie":
            raw_value = self._request_resolver.cookie_value(alias)
            return self._coerce_optional(annotation, raw_value)
        if field_kind == "body":
            body = await self._request_resolver.body()
            if isinstance(body, dict):
                if alias in body:
                    return self._coerce_optional(annotation, body[alias])
                if getattr(field_info, "embed", False):
                    return _ResolvedParameter(found=False)
                return self._coerce_optional(annotation, body)
            if body is not None:
                return self._coerce_optional(annotation, body)
        return _ResolvedParameter(found=False)

    async def _resolve_from_inferred_request(
        self,
        parameter: inspect.Parameter,
        annotation: Any,
    ) -> _ResolvedParameter:
        path_params = self._request_resolver.path_params()
        if parameter.name in path_params:
            return self._coerce_optional(annotation, path_params[parameter.name])

        query_values = self._request_resolver.query_values(parameter.name)
        if query_values:
            raw_value = _pick_query_value(query_values, annotation)
            return self._coerce_optional(annotation, raw_value)

        return _ResolvedParameter(found=False)

    def _coerce_optional(self, annotation: Any, raw_value: Any) -> _ResolvedParameter:
        if raw_value is None:
            return _ResolvedParameter(found=False)
        return _ResolvedParameter(
            found=True,
            value=_coerce_value(annotation, raw_value),
        )


@asynccontextmanager
async def provide_dependencies(
    func: Callable[..., Any],
    kwargs: Optional[dict[str, Any]] = None,
    *,
    request: Any | None = None,
    path: str | None = None,
    dependency_overrides: dict[Callable[..., Any], Callable[..., Any]] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """
    Resolve the arguments needed to call ``func`` within an async context.

    Parameters:
        func: Target callable whose dependency-marked parameters should be
            resolved.
        kwargs: Optional seed values supplied by the caller. These values take
            precedence over inferred request data.
        request: Optional request-like object used for request-aware parameter
            extraction.
        path: Optional route template used when deriving path parameters from
            the request URL.
        dependency_overrides: Optional dependency replacement mapping, commonly
            used by tests.

    Yields:
        A dictionary of keyword arguments that can be passed directly to
        ``func``.

    Metadata:
        context_lifetime: dependency resources remain open until the surrounding
            async context exits
        supported_markers: ``mountaineer_di.Depends`` and ``fastapi.Depends``
    """

    resolver = DependencyResolver(
        kwargs,
        request=request,
        path=path,
        dependency_overrides=dependency_overrides,
    )
    try:
        call_kwargs = await resolver.build_call_kwargs(func)
    except BaseException as exc:
        await resolver.exit(type(exc), exc, exc.__traceback__)
        raise

    try:
        yield call_kwargs
    except BaseException as exc:
        suppress = await resolver.exit(type(exc), exc, exc.__traceback__)
        if not suppress:
            raise
    else:
        await resolver.close()


@asynccontextmanager
async def get_function_dependencies(
    *,
    callable: Callable[..., Any],
    kwargs: Optional[dict[str, Any]] = None,
    url: str | None = None,
    request: Any | None = None,
    dependency_overrides: dict[Callable[..., Any], Callable[..., Any]] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """
    Resolve dependencies using the ``url`` parameter name for route templates.

    Parameters:
        callable: Target callable whose dependency graph should be resolved.
        kwargs: Optional seed values supplied by the caller.
        url: Optional route template forwarded to ``provide_dependencies`` as
            ``path`` for Mountaineer compatibility.
        request: Optional request-like object used for request-aware parameter
            extraction.
        dependency_overrides: Optional dependency replacement mapping.

    Yields:
        A dictionary of resolved keyword arguments for ``callable``.
    """

    async with provide_dependencies(
        callable,
        kwargs,
        request=request,
        path=url,
        dependency_overrides=dependency_overrides,
    ) as values:
        yield values
