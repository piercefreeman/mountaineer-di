from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class _ResolvedParameter:
    found: bool
    value: Any = None


class _RequestResolver:
    def __init__(self, request: Any | None, path_template: str | None) -> None:
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


def _match_path(path_template: str, request_path: str) -> dict[str, str]:
    pattern_parts: list[str] = []
    cursor = 0
    for match in re.finditer(r"{([^}:]+)(?::[^}]+)?}", path_template):
        pattern_parts.append(re.escape(path_template[cursor : match.start()]))
        converter_name = match.group(1)
        converter_type = (
            match.group(0).split(":", 1)[1][:-1] if ":" in match.group(0) else ""
        )
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
