from .resolver import Depend as Depend
from .resolver import DependenciesBase as DependenciesBase
from .resolver import DependencyResolver as DependencyResolver
from .resolver import Depends as Depends
from .fastapi_compat import fetch_recent_stable_fastapi_versions as fetch_recent_stable_fastapi_versions
from .resolver import get_function_dependencies as get_function_dependencies
from .resolver import isolate_dependency_only_function as isolate_dependency_only_function
from .resolver import provide_dependencies as provide_dependencies
from .resolver import strip_depends_from_signature as strip_depends_from_signature

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
