from __future__ import annotations

import inspect
from typing import Any

try:
    import fastapi.params as _fastapi_params_module
except ImportError:
    _fastapi_params: Any | None = None
else:
    _fastapi_params = _fastapi_params_module

try:
    from fastapi import Request as _FastAPIRequestType
except ImportError:
    _FastAPIRequest: type[Any] | None = None
else:
    _FastAPIRequest = _FastAPIRequestType

try:
    from starlette.requests import Request as _StarletteRequestType
except ImportError:
    _StarletteRequest: type[Any] | None = None
else:
    _StarletteRequest = _StarletteRequestType

_REQUEST_TYPES: tuple[type[Any], ...] = tuple(
    request_type
    for request_type in (_StarletteRequest, _FastAPIRequest)
    if inspect.isclass(request_type)
)


def _is_fastapi_depends_instance(value: Any) -> bool:
    return _fastapi_params is not None and isinstance(value, _fastapi_params.Depends)


def _is_fastapi_field_info_instance(value: Any) -> bool:
    return _fastapi_params is not None and isinstance(
        value, (_fastapi_params.Param, _fastapi_params.Body)
    )


def _fastapi_field_info_kind(value: Any) -> str | None:
    if _fastapi_params is None:
        return None
    if isinstance(value, _fastapi_params.Path):
        return "path"
    if isinstance(value, _fastapi_params.Query):
        return "query"
    if isinstance(value, _fastapi_params.Header):
        return "header"
    if isinstance(value, _fastapi_params.Cookie):
        return "cookie"
    if isinstance(value, _fastapi_params.Body):
        return "body"
    return None


def _is_optional_request_annotation(annotation: Any) -> bool:
    if annotation is inspect.Parameter.empty or not inspect.isclass(annotation):
        return False

    for request_type in _REQUEST_TYPES:
        try:
            if issubclass(annotation, request_type):
                return True
        except TypeError:
            return False
    return False
