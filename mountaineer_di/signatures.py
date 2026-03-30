from __future__ import annotations

from inspect import Signature, signature
from typing import Any, Callable

from .annotations import _dependency_marker, _get_parameter_hints


def isolate_dependency_only_function(
    original_fn: Callable[..., Any],
) -> Callable[..., Any]:
    """
    Create a shim whose signature only contains dependency parameters.

    Parameters:
        original_fn: Callable to inspect for dependency-marked parameters.

    Returns:
        An async no-op callable with a synthetic signature containing only the
        parameters marked with ``Depends``.

    Metadata:
        supported_markers: default-value ``Depends`` and ``Annotated`` metadata
        primary_use: compatibility with tools that should inspect only injected
            parameters
    """

    sig = signature(original_fn)
    hints = _get_parameter_hints(original_fn)
    dependency_params = [
        parameter
        for parameter in sig.parameters.values()
        if _dependency_marker(
            parameter,
            hints.get(parameter.name, parameter.annotation),
        )
        is not None
    ]

    async def mock_fn(**deps: Any) -> Any:
        return None

    setattr(mock_fn, "__signature__", sig.replace(parameters=dependency_params))
    return mock_fn


def strip_depends_from_signature(original_fn: Callable[..., Any]) -> Signature:
    """
    Remove dependency parameters from ``original_fn``'s public signature.

    Parameters:
        original_fn: Callable whose signature should be filtered.

    Returns:
        A new :class:`inspect.Signature` containing only user-supplied
        parameters.

    Metadata:
        supported_markers: default-value ``Depends`` and ``Annotated`` metadata
        primary_use: expose the caller-facing portion of a function signature
    """

    sig = signature(original_fn)
    hints = _get_parameter_hints(original_fn)
    non_dependency_params = [
        parameter
        for parameter in sig.parameters.values()
        if _dependency_marker(
            parameter,
            hints.get(parameter.name, parameter.annotation),
        )
        is None
    ]
    return sig.replace(parameters=non_dependency_params)
