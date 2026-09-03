# tests/integration/test_cors_policy.py
"""Who may call the workstation API from a browser (VRT-16).

This API binds loopback, which is often mistaken for "only this app can reach
it". Loopback is reachable from the browser of the person sitting at the
machine, and this API serves patient records and starts and stops recordings.
CORS is the control that decides which page may do that.

The defect these tests were written for: the packaged desktop app loaded its
frontend with `loadFile()`, giving the renderer a `file://` page whose origin is
the opaque `null`. Every fetch it made to the backend was cross-origin from an
origin the allow-list does not contain, so the browser discarded the response --
**the packaged app's UI could not talk to its own backend**. Nobody had hit it,
because the packaged app has never been buildable (see VRT-2).

The fix is not to allow `null`. `null` is also the origin of every sandboxed
iframe on every website, so allowing it would let any page the researcher
visits drive this API. The packaged shell registers an `app://` scheme instead,
which is the origin `settings.py` has listed all along.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from src.config import ApiSettings, PathSettings, Settings
from src.interfaces.api.app import create_app
from src.interfaces.api.container import build_container

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_ROUTE = "/api/sync/status"


class _Offline:
    def __init__(self) -> None:
        import requests

        self.RequestException = requests.RequestException

    def get(self, _url: str, *_a: Any, **_k: Any) -> Any:
        raise self.RequestException("offline")

    def post(self, _url: str, *_a: Any, **_k: Any) -> Any:
        raise self.RequestException("offline")


def _client(tmp_path: Path, settings: Settings | None = None) -> TestClient:
    settings = settings or Settings(paths=PathSettings(data_root=tmp_path))
    return TestClient(create_app(build_container(settings, http=_Offline())))


def _allowed_origin_header(client: TestClient, origin: str) -> str | None:
    response = client.get(PROBE_ROUTE, headers={"Origin": origin})
    assert response.status_code == 200, "the route itself must work regardless of CORS"
    return response.headers.get("access-control-allow-origin")


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:5173", "http://127.0.0.1:5173", "app://."],
)
def test_the_two_ways_the_app_is_actually_run_are_allowed(tmp_path: Path, origin: str) -> None:
    """The Vite dev server, and the packaged shell's own scheme."""
    assert _allowed_origin_header(_client(tmp_path), origin) == origin


def test_a_file_page_is_refused(tmp_path: Path) -> None:
    """`null` must never be allowed, and this is the test that says why.

    Adding it would fix the packaged app in one line -- and would also hand the
    API to every sandboxed iframe on every website, which shares that origin.
    If this test is ever failing because someone added "null" to
    `allowed_origins`, the fix they wanted is in electron/main.js.
    """
    assert _allowed_origin_header(_client(tmp_path), "null") is None


@pytest.mark.parametrize(
    "origin",
    ["http://evil.example", "https://evil.example", "http://localhost:5174", "app://elsewhere"],
)
def test_everything_else_is_refused(tmp_path: Path, origin: str) -> None:
    assert _allowed_origin_header(_client(tmp_path), origin) is None


def test_credentialed_requests_are_not_invited(tmp_path: Path) -> None:
    """Nothing sends cookies, so nothing asks for permission to.

    `allow_credentials=True` was set while there is not one `credentials:`
    option in the frontend and this API sets no cookies -- auth state lives in
    the licence cache, server-side.
    """
    response = _client(tmp_path).get(PROBE_ROUTE, headers={"Origin": "app://."})

    assert "access-control-allow-credentials" not in response.headers


def test_a_preflight_advertises_only_the_verbs_the_api_uses(tmp_path: Path) -> None:
    """`allow_methods=["*"]` was the previous value."""
    response = _client(tmp_path).options(
        PROBE_ROUTE,
        headers={
            "Origin": "app://.",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    allowed = {m.strip() for m in response.headers["access-control-allow-methods"].split(",")}
    assert allowed == {"GET", "POST", "PUT", "DELETE", "OPTIONS"}
    assert "*" not in allowed


def test_the_allow_list_is_configuration_not_a_literal(tmp_path: Path) -> None:
    """A lab that serves the UI from somewhere else can say so.

    Proves the middleware reads settings rather than a hardcoded tuple, which
    is what makes narrowing it in deployment possible at all.
    """
    settings = Settings(
        paths=PathSettings(data_root=tmp_path),
        api=ApiSettings(allowed_origins=("https://studio.lab.internal",)),
    )
    client = _client(tmp_path, settings)

    assert _allowed_origin_header(client, "https://studio.lab.internal") == (
        "https://studio.lab.internal"
    )
    assert _allowed_origin_header(client, "http://localhost:5173") is None


# ─────────────────────────────────────────────────────────────────────────────
# The other half of the fix lives in JavaScript
# ─────────────────────────────────────────────────────────────────────────────


def test_the_packaged_shell_serves_itself_from_the_origin_the_api_allows() -> None:
    """The Python and the Electron halves must not drift apart.

    `app://.` is in `allowed_origins`; it is only a real origin because
    electron/main.js registers the scheme and loads from it. Either half alone
    is useless, and the failure mode of losing the JavaScript half is a packaged
    app whose UI silently cannot reach its backend -- which is precisely the
    state this ticket found.
    """
    source = (REPO_ROOT / "electron/main.js").read_text(encoding="utf-8")
    # Comment lines stripped: this file explains the bug it fixes, and naming
    # `loadFile()` in that explanation is not the same as calling it.
    main_js = "\n".join(line for line in source.splitlines() if not line.strip().startswith("//"))

    assert "registerSchemesAsPrivileged" in main_js, "the app:// scheme is not registered"
    assert re.search(r"protocol\.handle\(", main_js), "nothing serves the app:// scheme"
    assert "loadURL(`${APP_SCHEME}://./index.html`)" in main_js, (
        "the packaged window is not loaded from the app:// origin"
    )
    assert "loadFile(" not in main_js, (
        "loadFile() gives the renderer a file:// page, whose origin is `null` -- "
        "the API refuses it, and it cannot be allowed without also allowing every "
        "sandboxed iframe on the web"
    )
    assert ApiSettings().allowed_origins.count("app://.") == 1, (
        "electron/main.js serves app:// but the API no longer allows it"
    )
