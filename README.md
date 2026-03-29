# mountaineer-di
Common dependency injection utilities for mountaineer &amp; friends.

This package provides a single dependency resolver that can replace the current
Mountaineer and Waymark implementations while remaining compatible with both
`mountaineer_di.Depends` and `fastapi.Depends`.

CI includes a FastAPI compatibility stage that queries PyPI at runtime and runs
the test suite against the 25 most recent stable FastAPI releases.
