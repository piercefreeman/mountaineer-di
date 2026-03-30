from __future__ import annotations

import inspect
from typing import Annotated, Any, Callable, get_args, get_origin, get_type_hints

from pydantic import TypeAdapter
from pydantic_core import PydanticUndefined

from .markers import _DependsMarker
from .optional_fastapi import (
    _is_fastapi_depends_instance,
    _is_fastapi_field_info_instance,
    _is_optional_request_annotation,
)

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
        return get_type_hints(
            target,
            globalns=globalns,
            localns=localns,
            include_extras=True,
        )
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
) -> Any | None:
    if isinstance(parameter.default, _DependsMarker) or _is_fastapi_depends_instance(
        parameter.default
    ):
        return parameter.default

    _, metadata = _annotation_metadata(annotation)
    for value in metadata:
        if isinstance(value, _DependsMarker) or _is_fastapi_depends_instance(value):
            return value
    return None


def _field_info(
    parameter: inspect.Parameter,
    annotation: Any,
) -> Any | None:
    if _is_fastapi_field_info_instance(parameter.default):
        return parameter.default

    _, metadata = _annotation_metadata(annotation)
    for value in metadata:
        if _is_fastapi_field_info_instance(value):
            return value
    return None


def _field_default(field_info: Any) -> Any:
    default = getattr(field_info, "default", PydanticUndefined)
    if default is PydanticUndefined:
        return _MISSING
    return default


def _callable_from_annotation(annotation: Any) -> Callable[..., Any] | None:
    candidate = _strip_annotated(annotation)
    return candidate if callable(candidate) else None


def _is_request_annotation(annotation: Any) -> bool:
    return _is_optional_request_annotation(annotation)


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
