from .fastapi_compat import (
    fetch_recent_stable_fastapi_versions as fetch_recent_stable_fastapi_versions,
)
from .resolver import (
    Depend as Depend,
    DependenciesBase as DependenciesBase,
    DependencyResolver as DependencyResolver,
    Depends as Depends,
    get_function_dependencies as get_function_dependencies,
    isolate_dependency_only_function as isolate_dependency_only_function,
    provide_dependencies as provide_dependencies,
    strip_depends_from_signature as strip_depends_from_signature,
)

__all__ = [
    "Depend",
    "DependenciesBase",
    "DependencyResolver",
    "Depends",
    "fetch_recent_stable_fastapi_versions",
    "get_function_dependencies",
    "isolate_dependency_only_function",
    "provide_dependencies",
    "strip_depends_from_signature",
]
