from mountaineer_di.fastapi_compat import (
    is_stable_release,
    minor_line,
    select_recent_stable_versions,
    stable_release_records,
)


def test_is_stable_release_filters_prereleases() -> None:
    assert is_stable_release("0.121.0")
    assert is_stable_release("0.121.0.post1")
    assert not is_stable_release("0.121.0rc1")
    assert not is_stable_release("0.121.0.dev1")
    assert not is_stable_release("0.121.0b1")


def test_minor_line_groups_patch_releases() -> None:
    assert minor_line("0.121.3") == "0.121"
    assert minor_line("0.121.3.post1") == "0.121"


def test_stable_release_records_sorts_by_upload_time_and_skips_yanked() -> None:
    releases = {
        "0.121.0": [
            {
                "upload_time_iso_8601": "2026-03-10T10:00:00.000000Z",
                "yanked": False,
            }
        ],
        "0.120.1": [
            {
                "upload_time_iso_8601": "2026-03-05T10:00:00.000000Z",
                "yanked": False,
            }
        ],
        "0.121.0rc1": [
            {
                "upload_time_iso_8601": "2026-03-12T10:00:00.000000Z",
                "yanked": False,
            }
        ],
        "0.120.0": [
            {
                "upload_time_iso_8601": "2026-03-01T10:00:00.000000Z",
                "yanked": True,
            }
        ],
    }

    assert stable_release_records(releases) == [
        ("2026-03-10T10:00:00.000000Z", "0.121.0"),
        ("2026-03-05T10:00:00.000000Z", "0.120.1"),
    ]


def test_select_recent_stable_versions_combines_patch_and_minor_buckets() -> None:
    releases = {
        "0.122.1": [
            {
                "upload_time_iso_8601": "2026-03-15T10:00:00.000000Z",
                "yanked": False,
            }
        ],
        "0.122.0": [
            {
                "upload_time_iso_8601": "2026-03-14T10:00:00.000000Z",
                "yanked": False,
            }
        ],
        "0.121.3": [
            {
                "upload_time_iso_8601": "2026-03-13T10:00:00.000000Z",
                "yanked": False,
            }
        ],
        "0.121.2": [
            {
                "upload_time_iso_8601": "2026-03-12T10:00:00.000000Z",
                "yanked": False,
            }
        ],
        "0.120.5": [
            {
                "upload_time_iso_8601": "2026-03-11T10:00:00.000000Z",
                "yanked": False,
            }
        ],
        "0.120.4": [
            {
                "upload_time_iso_8601": "2026-03-10T10:00:00.000000Z",
                "yanked": False,
            }
        ],
        "0.119.9": [
            {
                "upload_time_iso_8601": "2026-03-09T10:00:00.000000Z",
                "yanked": False,
            }
        ],
        "0.118.2": [
            {
                "upload_time_iso_8601": "2026-03-08T10:00:00.000000Z",
                "yanked": False,
            }
        ],
        "0.121.4rc1": [
            {
                "upload_time_iso_8601": "2026-03-16T10:00:00.000000Z",
                "yanked": False,
            }
        ],
    }

    assert select_recent_stable_versions(
        releases,
        patch_limit=3,
        minor_limit=4,
    ) == [
        "0.122.1",
        "0.122.0",
        "0.121.3",
        "0.120.5",
        "0.119.9",
    ]
