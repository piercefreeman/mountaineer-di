from __future__ import annotations

from .markers import Depends
from .resolver_core import (
    DependencyResolver,
    get_function_dependencies,
    provide_dependencies,
)
from .signatures import (
    isolate_dependency_only_function,
    strip_depends_from_signature,
)

__all__ = [
    "DependencyResolver",
    "Depends",
    "get_function_dependencies",
    "isolate_dependency_only_function",
    "provide_dependencies",
    "strip_depends_from_signature",
]
