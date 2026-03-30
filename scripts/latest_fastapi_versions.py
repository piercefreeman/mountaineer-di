#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "click>=8.1,<9",
# ]
# ///
from __future__ import annotations

import json
import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.fastapi_release_helper import fetch_recent_stable_fastapi_versions


@click.command()
@click.option(
    "--patch-count",
    type=click.IntRange(min=1),
    default=10,
    show_default=True,
    help="Number of recent stable patch releases to return.",
)
@click.option(
    "--minor-count",
    type=click.IntRange(min=1),
    default=50,
    show_default=True,
    help="Number of recent minor lines to include at their latest stable release.",
)
def main(patch_count: int, minor_count: int) -> None:
    versions = fetch_recent_stable_fastapi_versions(
        patch_limit=patch_count,
        minor_limit=minor_count,
    )
    click.echo(json.dumps(versions))


if __name__ == "__main__":
    main()
