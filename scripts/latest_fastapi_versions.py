#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mountaineer_di.fastapi_compat import fetch_recent_stable_fastapi_versions


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch the most recent stable FastAPI releases from PyPI."
    )
    parser.add_argument(
        "--patch-count",
        type=int,
        default=10,
        help="Number of recent stable patch releases to return.",
    )
    parser.add_argument(
        "--minor-count",
        type=int,
        default=50,
        help="Number of recent minor lines to include at their latest stable release.",
    )
    args = parser.parse_args()

    versions = fetch_recent_stable_fastapi_versions(
        patch_limit=args.patch_count,
        minor_limit=args.minor_count,
    )
    print(json.dumps(versions))


if __name__ == "__main__":
    main()
