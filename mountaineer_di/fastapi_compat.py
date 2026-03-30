from __future__ import annotations

import json
import re
from typing import Any
from urllib.request import Request, urlopen

PYPI_FASTAPI_JSON_URL = "https://pypi.org/pypi/fastapi/json"
STABLE_RELEASE_RE = re.compile(r"^\d+(?:\.\d+)*(?:\.post\d+)?$")


def is_stable_release(version: str) -> bool:
    return bool(STABLE_RELEASE_RE.fullmatch(version))


def minor_line(version: str) -> str:
    parts = version.split(".")
    if len(parts) < 2:
        return version
    return ".".join(parts[:2])


def stable_release_records(
    releases: dict[str, list[dict[str, Any]]],
) -> list[tuple[str, str]]:
    ranked_versions: list[tuple[str, str]] = []
    for version, files in releases.items():
        if not is_stable_release(version):
            continue

        non_yanked_files = [file for file in files if not file.get("yanked", False)]
        if not non_yanked_files:
            continue

        latest_upload = max(
            (file.get("upload_time_iso_8601") or file.get("upload-time") or "")
            for file in non_yanked_files
        )
        if not latest_upload:
            continue

        ranked_versions.append((latest_upload, version))

    ranked_versions.sort(reverse=True)
    return ranked_versions


def select_recent_stable_versions(
    releases: dict[str, list[dict[str, Any]]],
    *,
    patch_limit: int = 10,
    minor_limit: int = 50,
) -> list[str]:
    ranked_versions = stable_release_records(releases)

    selected_versions: list[str] = []
    seen_versions: set[str] = set()

    for _, version in ranked_versions[:patch_limit]:
        selected_versions.append(version)
        seen_versions.add(version)

    seen_minor_lines: set[str] = set()
    minor_versions_selected = 0
    for _, version in ranked_versions:
        current_minor_line = minor_line(version)
        if current_minor_line in seen_minor_lines:
            continue

        seen_minor_lines.add(current_minor_line)
        minor_versions_selected += 1

        if version not in seen_versions:
            selected_versions.append(version)
            seen_versions.add(version)

        if minor_versions_selected >= minor_limit:
            break

    return selected_versions


def fetch_recent_stable_fastapi_versions(
    *,
    patch_limit: int = 10,
    minor_limit: int = 50,
    url: str = PYPI_FASTAPI_JSON_URL,
) -> list[str]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "mountaineer-di-fastapi-compat/1.0",
        },
    )
    with urlopen(request) as response:
        payload = json.load(response)
    releases = payload.get("releases", {})
    if not isinstance(releases, dict):
        raise ValueError("Unexpected PyPI payload: missing releases mapping")
    return select_recent_stable_versions(
        releases,
        patch_limit=patch_limit,
        minor_limit=minor_limit,
    )
