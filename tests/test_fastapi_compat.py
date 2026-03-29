from mountaineer_di.fastapi_compat import (
    is_stable_release,
    select_recent_stable_versions,
)


def test_is_stable_release_filters_prereleases() -> None:
    assert is_stable_release("0.121.0")
    assert is_stable_release("0.121.0.post1")
    assert not is_stable_release("0.121.0rc1")
    assert not is_stable_release("0.121.0.dev1")
    assert not is_stable_release("0.121.0b1")


def test_select_recent_stable_versions_sorts_by_upload_time_and_skips_yanked() -> None:
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

    assert select_recent_stable_versions(releases, limit=2) == ["0.121.0", "0.120.1"]
