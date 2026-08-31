"""The API's route contract, pinned exactly (VRT-10).

Every other test in this suite exercises behaviour. This one pins the *surface*:
the precise set of method-and-path pairs the workstation exposes.

It exists because VRT-10 moved all 29 routes out of ``src/main.py`` into eight
router modules, and VRT-11 through VRT-14 will move the code behind them again.
The failure mode those refactors risk is not a broken route -- a broken route
fails loudly in the tests above -- it is a route that quietly stops being
registered at all, because a router was not mounted or an import was dropped. A
missing route produces 404s in the desktop app and nothing at all in a test
suite that only asserts on the routes it remembers to call.

Comparing against a literal list is deliberate. Deriving the expected set from
the app would make the test tautological.
"""

from __future__ import annotations

from typing import Any

#: The 29 operations, verified identical before and after the VRT-10 split by
#: diffing the generated OpenAPI document: same paths, same methods, same
#: request and response schemas, differing only in the `tags` the split added.
EXPECTED_OPERATIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/upload-telemetry"),
        ("GET", "/api/sessions"),
        ("GET", "/api/sessions/{session_id}"),
        ("PUT", "/api/sessions/{session_id}"),
        ("GET", "/api/sessions/{session_id}/telemetry"),
        ("POST", "/api/sessions/{session_id}/questionnaire"),
        ("POST", "/api/recording/start"),
        ("POST", "/api/recording/stop"),
        ("POST", "/api/session/scene"),
        ("POST", "/api/session/mark"),
        ("POST", "/api/session/haptic"),
        ("POST", "/api/session/target"),
        ("GET", "/api/patients"),
        ("POST", "/api/patients"),
        ("PUT", "/api/patients/{patient_id}"),
        ("DELETE", "/api/patients/{patient_id}"),
        ("POST", "/api/patients/{patient_id}/withdraw-consent"),
        ("GET", "/api/patients/{patient_id}/sessions"),
        ("POST", "/api/auth/register"),
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/logout"),
        ("GET", "/api/auth/session"),
        ("GET", "/api/license/status"),
        ("POST", "/api/license/activate"),
        ("GET", "/api/sync/status"),
        ("POST", "/api/sync/retry"),
        ("POST", "/api/sync/backfill"),
        ("GET", "/api/config/central-server"),
        ("POST", "/api/config/central-server"),
    }
)


def _operations(app: Any) -> set[tuple[str, str]]:
    """Read the surface from the OpenAPI document rather than ``app.routes``.

    ``app.routes`` stopped being a reliable enumeration in FastAPI 0.141:
    ``include_router`` now appends an internal ``_IncludedRouter`` wrapper that
    carries no ``path``, so counting routes there silently returns zero for an
    app assembled from routers. The generated schema is what clients actually
    consume, which makes it the honest thing to assert on anyway.
    """
    schema = app.openapi()
    return {
        (method.upper(), path)
        for path, item in schema["paths"].items()
        for method in item
        if path.startswith("/api")
    }


def test_every_expected_route_is_registered(workstation: Any) -> None:
    """A route that vanishes during a refactor must fail here, not in the app."""
    missing = EXPECTED_OPERATIONS - _operations(workstation.app)

    assert not missing, f"routes disappeared: {sorted(missing)}"


def test_no_route_was_added_unnoticed(workstation: Any) -> None:
    """New surface is fine, but it should be a decision, not a side effect.

    Add it to EXPECTED_OPERATIONS in the same commit that adds the route, and
    add a characterisation test for it while you are there.
    """
    added = _operations(workstation.app) - EXPECTED_OPERATIONS

    assert not added, f"undeclared routes: {sorted(added)}"


def test_the_app_can_be_built_more_than_once(workstation: Any) -> None:
    """create_app() is a factory, not a module-level singleton.

    This is the property the whole decomposition is aimed at. Before VRT-10 the
    app was constructed at import, so a process could hold exactly one -- which
    is why the API had no tests. Two independent instances is the seam VRT-12
    needs to inject fakes rather than monkeypatch module attributes.
    """
    from src.interfaces.api.app import create_app

    first, second = create_app(), create_app()

    assert first is not second
    assert _operations(first) == _operations(second) == EXPECTED_OPERATIONS


def test_routes_carry_tags_so_the_docs_group_sensibly(workstation: Any) -> None:
    """The one intended difference the split made to the OpenAPI document."""
    schema = workstation.app.openapi()
    tagged = [
        operation.get("tags")
        for path, item in schema["paths"].items()
        for operation in item.values()
        if path.startswith("/api")
    ]

    assert all(tagged), "some operation has no tag"
    assert {t for tags in tagged for t in tags} == {
        "sessions",
        "questionnaires",
        "recording",
        "patients",
        "auth",
        "licence",
        "sync",
        "config",
    }
