from __future__ import annotations

import inspect
import re
import warnings
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass
from inspect import Parameter, Signature, signature
from typing import Annotated, Any, AsyncIterator, Callable, Optional, get_args, get_origin, get_type_hints

from fastapi import Depends as Depends
from fastapi import Request, params as fastapi_params
from pydantic import TypeAdapter
from pydantic_core import PydanticUndefined

Depend = Depends


class DependenciesBaseMeta(type):
    """
    Compatibility shim for Mountaineer's legacy dependency wrapper classes.
    """

    def __new__(cls, name, bases, namespace, **kwargs):
        if name != "DependenciesBase":
            warnings.warn(
                (
                    "DependenciesBase is deprecated and will be removed in a future version.\n"
                    "Import modules to form dependencies. See mountaineer.dependencies.core for an example."
                ),
                DeprecationWarning,
                stacklevel=2,
            )

        for attr_name, attr_value in namespace.items():
            if isinstance(attr_value, staticmethod):
                raise TypeError(
                    f"Static methods are not allowed in dependency wrapper '{name}'. Found static method: '{attr_name}'."
                )
        return super().__new__(cls, name, bases, namespace, **kwargs)


class DependenciesBase(metaclass=DependenciesBaseMeta):
    pass


@dataclass
class _ResolvedParameter:
    found: bool
    value: Any = None


class _RequestResolver:
    def __init__(self, request: Request | None, path_template: str | None) -> None:
        self.request = request
        self.path_template = path_template
        self._path_params: dict[str, Any] | None = None
        self._body_loaded = False
        self._body: Any = None

    def path_params(self) -> dict[str, Any]:
        if self._path_params is not None:
            return self._path_params
        if self.request is None:
            self._path_params = {}
            return self._path_params

        scope_params = self.request.scope.get("path_params")
        if isinstance(scope_params, dict) and scope_params:
            self._path_params = dict(scope_params)
            return self._path_params

        request_path = self.request.scope.get("path", self.request.url.path)
        if not self.path_template:
            self._path_params = {}
            return self._path_params

        self._path_params = _match_path(self.path_template, request_path)
        return self._path_params

    def query_values(self, name: str) -> list[str]:
        if self.request is None:
            return []
        return list(self.request.query_params.getlist(name))

    def header_value(self, name: str) -> str | None:
        if self.request is None:
            return None
        return self.request.headers.get(name)

    def cookie_value(self, name: str) -> str | None:
        if self.request is None:
            return None
        return self.request.cookies.get(name)

    async def body(self) -> Any:
        if self._body_loaded:
            return self._body
        self._body_loaded = True
        if self.request is None:
            self._body = None
            return None
        try:
            self._body = await self.request.json()
        except Exception:
            self._body = None
        return self._body


class DependencyResolver:
    """
    Standalone dependency resolver that supports both plain call graphs and
    request-bound parameter extraction.
    """

    def __init__(
        self,
        initial_kwargs: Optional[dict[str, Any]] = None,
        *,
        request: Request | None = None,
        path: str | None = None,
        dependency_overrides: dict[Callable[..., Any], Callable[..., Any]] | None = None,
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
        await self._stack.aclose()

    async def build_call_kwargs(self, func: Callable[..., Any]) -> dict[str, Any]:
        func_signature = signature(func)
        hints = _get_parameter_hints(func)

        await self._seed_non_dependency_context(func_signature, hints)

        call_kwargs: dict[str, Any] = {}
        func_name = getattr(func, "__name__", func.__class__.__name__)
        for name, parameter in func_signature.parameters.items():
            if parameter.kind in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD):
                continue

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
        marker: fastapi_params.Depends,
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
            resolved = await self._resolve_from_field_info(parameter, annotation, field_info)
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
        field_info: fastapi_params.Param | fastapi_params.Body,
    ) -> _ResolvedParameter:
        alias = getattr(field_info, "alias", None) or parameter.name
        if isinstance(field_info, fastapi_params.Path):
            raw_value = self._request_resolver.path_params().get(alias)
            return self._coerce_optional(annotation, raw_value)
        if isinstance(field_info, fastapi_params.Query):
            raw_value = _pick_query_value(self._request_resolver.query_values(alias), annotation)
            return self._coerce_optional(annotation, raw_value)
        if isinstance(field_info, fastapi_params.Header):
            header_name = alias
            if header_name == parameter.name and getattr(field_info, "convert_underscores", True):
                header_name = header_name.replace("_", "-")
            raw_value = self._request_resolver.header_value(header_name)
            return self._coerce_optional(annotation, raw_value)
        if isinstance(field_info, fastapi_params.Cookie):
            raw_value = self._request_resolver.cookie_value(alias)
            return self._coerce_optional(annotation, raw_value)
        if isinstance(field_info, fastapi_params.Body):
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
        return _ResolvedParameter(found=True, value=_coerce_value(annotation, raw_value))


_MISSING = object()


def _get_parameter_hints(func: Callable[..., Any]) -> dict[str, Any]:
    target = getattr(func, "__func__", func)
    globalns = dict(getattr(target, "__globals__", {}))
    localns: dict[str, Any] = {}

    try:
        closure_vars = inspect.getclosurevars(target)
    except Exception:
        closure_vars = None

    if closure_vars is not None:
        globalns.update(closure_vars.globals)
        localns.update(closure_vars.nonlocals)

    try:
        return get_type_hints(target, globalns=globalns, localns=localns, include_extras=True)
    except Exception:
        return {}


def _annotation_metadata(annotation: Any) -> tuple[Any, tuple[Any, ...]]:
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        return args[0], tuple(args[1:])
    return annotation, ()


def _strip_annotated(annotation: Any) -> Any:
    stripped, _ = _annotation_metadata(annotation)
    return stripped


def _dependency_marker(
    parameter: inspect.Parameter,
    annotation: Any,
) -> fastapi_params.Depends | None:
    if isinstance(parameter.default, fastapi_params.Depends):
        return parameter.default

    _, metadata = _annotation_metadata(annotation)
    for value in metadata:
        if isinstance(value, fastapi_params.Depends):
            return value
    return None


def _field_info(
    parameter: inspect.Parameter,
    annotation: Any,
) -> fastapi_params.Param | fastapi_params.Body | None:
    if isinstance(parameter.default, (fastapi_params.Param, fastapi_params.Body)):
        return parameter.default

    _, metadata = _annotation_metadata(annotation)
    for value in metadata:
        if isinstance(value, (fastapi_params.Param, fastapi_params.Body)):
            return value
    return None


def _field_default(field_info: fastapi_params.Param | fastapi_params.Body) -> Any:
    default = getattr(field_info, "default", PydanticUndefined)
    if default is PydanticUndefined:
        return _MISSING
    return default


def _callable_from_annotation(annotation: Any) -> Callable[..., Any] | None:
    candidate = _strip_annotated(annotation)
    return candidate if callable(candidate) else None


def _is_request_annotation(annotation: Any) -> bool:
    if annotation is inspect.Parameter.empty:
        return False
    return inspect.isclass(annotation) and issubclass(annotation, Request)


def _pick_query_value(values: list[str], annotation: Any) -> Any:
    if not values:
        return None
    plain_annotation = _strip_annotated(annotation)
    origin = get_origin(plain_annotation)
    if origin in (list, set, tuple):
        return values
    return values[-1]


def _coerce_value(annotation: Any, raw_value: Any) -> Any:
    plain_annotation = _strip_annotated(annotation)
    if plain_annotation in (inspect.Parameter.empty, Any):
        return raw_value
    if _is_request_annotation(plain_annotation):
        return raw_value
    try:
        return TypeAdapter(plain_annotation).validate_python(raw_value)
    except Exception:
        return raw_value


def _match_path(path_template: str, request_path: str) -> dict[str, str]:
    pattern_parts: list[str] = []
    cursor = 0
    for match in re.finditer(r"{([^}:]+)(?::[^}]+)?}", path_template):
        pattern_parts.append(re.escape(path_template[cursor : match.start()]))
        converter_name = match.group(1)
        converter_type = match.group(0).split(":", 1)[1][:-1] if ":" in match.group(0) else ""
        if converter_type == "path":
            pattern_parts.append(f"(?P<{converter_name}>.+)")
        else:
            pattern_parts.append(f"(?P<{converter_name}>[^/]+)")
        cursor = match.end()
    pattern_parts.append(re.escape(path_template[cursor:]))

    match = re.fullmatch("".join(pattern_parts), request_path)
    if not match:
        return {}
    return match.groupdict()


@asynccontextmanager
async def provide_dependencies(
    func: Callable[..., Any],
    kwargs: Optional[dict[str, Any]] = None,
    *,
    request: Request | None = None,
    path: str | None = None,
    dependency_overrides: dict[Callable[..., Any], Callable[..., Any]] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    resolver = DependencyResolver(
        kwargs,
        request=request,
        path=path,
        dependency_overrides=dependency_overrides,
    )
    try:
        call_kwargs = await resolver.build_call_kwargs(func)
        yield call_kwargs
    finally:
        await resolver.close()


@asynccontextmanager
async def get_function_dependencies(
    *,
    callable: Callable[..., Any],
    kwargs: Optional[dict[str, Any]] = None,
    url: str | None = None,
    request: Request | None = None,
    dependency_overrides: dict[Callable[..., Any], Callable[..., Any]] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    async with provide_dependencies(
        callable,
        kwargs,
        request=request,
        path=url,
        dependency_overrides=dependency_overrides,
    ) as values:
        yield values


def isolate_dependency_only_function(original_fn: Callable[..., Any]) -> Callable[..., Any]:
    sig = signature(original_fn)
    hints = _get_parameter_hints(original_fn)
    dependency_params = [
        parameter
        for parameter in sig.parameters.values()
        if _dependency_marker(parameter, hints.get(parameter.name, parameter.annotation))
        is not None
    ]

    async def mock_fn(**deps: Any) -> Any:
        return None

    mock_fn.__signature__ = sig.replace(parameters=dependency_params)  # type: ignore[attr-defined]
    return mock_fn


def strip_depends_from_signature(original_fn: Callable[..., Any]) -> Signature:
    sig = signature(original_fn)
    hints = _get_parameter_hints(original_fn)
    non_dependency_params = [
        parameter
        for parameter in sig.parameters.values()
        if _dependency_marker(parameter, hints.get(parameter.name, parameter.annotation))
        is None
    ]
    return sig.replace(parameters=non_dependency_params)
