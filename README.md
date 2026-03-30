# mountaineer-di
Common dependency injection utilities for mountaineer &amp; friends.

This package provides a single dependency resolver that can replace the current
Mountaineer and Waymark implementations while remaining compatible with both
`mountaineer_di.Depends` and `fastapi.Depends`.

CI includes a FastAPI compatibility stage that queries PyPI at runtime and runs
the test suite against the 25 most recent stable FastAPI releases.

Development commands are available through the repo `Makefile`, with `lint`,
`ci-lint`, `lint-ruff`, `lint-ty`, and `test` targets following the same
pattern as sibling Mountaineer repositories.
