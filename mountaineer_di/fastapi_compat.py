from __future__ import annotations

import json
import re
from typing import Any
from urllib.request import Request, urlopen

PYPI_FASTAPI_JSON_URL = "https://pypi.org/pypi/fastapi/json"
STABLE_RELEASE_RE = re.compile(r"^\d+(?:\.\d+)*(?:\.post\d+)?$")


def is_stable_release(version: str) -> bool:
    return bool(STABLE_RELEASE_RE.fullmatch(version))


def select_recent_stable_versions(
    releases: dict[str, list[dict[str, Any]]],
    *,
    limit: int = 25,
) -> list[str]:
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
    return [version for _, version in ranked_versions[:limit]]


def fetch_recent_stable_fastapi_versions(
    *,
    limit: int = 25,
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
    return select_recent_stable_versions(releases, limit=limit)
