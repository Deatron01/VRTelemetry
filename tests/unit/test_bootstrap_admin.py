"""The first admin must be creatable, or the product cannot be used at all.

``POST /auth/register`` always creates a ``researcher``, and promotion needs an
admin session. On a fresh hub that is a closed loop over HTTP: no admin exists,
so no admin can be made, so no licence can be issued, so no workstation can
activate. ``src/license_service/bootstrap_admin.py`` is the only way out of it,
which makes these tests a check on whether the product boots at all rather than
on a utility script.

They did not exist before VRT-25, because the module was four ``input()`` calls
and there was nothing a test could drive.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from src.license_service import bootstrap_admin
from src.license_service.auth_manager import AuthManager


@pytest.fixture
def hub_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A data root with nothing in it -- the state a new hub machine is in."""
    monkeypatch.setenv("VRT_PATHS__DATA_ROOT", str(tmp_path))
    from src.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield tmp_path
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _auth(hub_root: Path) -> AuthManager:
    from src.config import get_settings

    return AuthManager(get_settings().paths.licenses_db)


def _role(hub_root: Path, email: str) -> str | None:
    from src.config import get_settings

    conn = sqlite3.connect(get_settings().paths.licenses_db)
    try:
        row = conn.execute("SELECT role FROM users WHERE email = ?", (email,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def test_it_creates_the_first_admin_on_a_database_that_does_not_exist_yet(
    hub_root: Path,
) -> None:
    """The schema is created here, not by a prior hub start.

    Requiring the hub to have run first would mean telling an operator to open
    the admin UI before the account that can open it exists.
    """
    from src.config import get_settings

    assert not Path(get_settings().paths.licenses_db).exists()

    code = bootstrap_admin.main(
        ["--email", "First@Lab.org", "--org", "Lab", "--password", "correcthorse"]
    )

    assert code == 0
    assert _role(hub_root, "first@lab.org") == "admin", "email should be normalised and admin"


def test_the_created_admin_can_actually_log_in_and_passes_the_admin_gate(
    hub_root: Path,
) -> None:
    """Not "a row says admin" -- the check the routes actually perform."""
    bootstrap_admin.main(["--email", "boss@lab.org", "--org", "Lab", "--password", "correcthorse"])

    auth = _auth(hub_root)
    session = auth.login("boss@lab.org", "correcthorse")

    assert session["ok"] is True
    assert auth.is_admin(session["session_token"]) is True


def test_it_promotes_an_existing_researcher_rather_than_refusing(hub_root: Path) -> None:
    """The common case: the operator registered through the UI first."""
    bootstrap_admin.main(["--email", "boss@lab.org", "--org", "Lab", "--password", "correcthorse"])
    auth = _auth(hub_root)
    auth.register("junior@lab.org", "correcthorse", "Lab")
    assert _role(hub_root, "junior@lab.org") == "researcher"

    assert bootstrap_admin.main(["--email", "junior@lab.org"]) == 0
    assert _role(hub_root, "junior@lab.org") == "admin"


def test_running_it_twice_is_a_success_and_not_a_second_account(hub_root: Path) -> None:
    """Idempotent, because an operator who is unsure will run it again."""
    args = ["--email", "boss@lab.org", "--org", "Lab", "--password", "correcthorse"]
    assert bootstrap_admin.main(args) == 0
    assert bootstrap_admin.main(args) == 0

    from src.config import get_settings

    conn = sqlite3.connect(get_settings().paths.licenses_db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM users WHERE email = ?", ("boss@lab.org",)
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_creating_a_new_account_without_an_org_fails_loudly(hub_root: Path) -> None:
    """Rather than inventing an organisation name the operator never chose."""
    code = bootstrap_admin.main(["--email", "boss@lab.org", "--password", "correcthorse"])

    assert code == 2
    assert _role(hub_root, "boss@lab.org") is None


def test_a_rejected_password_is_reported_and_creates_nothing(hub_root: Path, capsys: Any) -> None:
    """AuthManager's minimum is 8 characters; the exit code has to carry that."""
    code = bootstrap_admin.main(["--email", "boss@lab.org", "--org", "Lab", "--password", "short"])

    assert code == 1
    assert "password_too_short" in capsys.readouterr().err
    assert _role(hub_root, "boss@lab.org") is None


def test_registration_over_http_still_cannot_mint_an_admin(hub_root: Path) -> None:
    """The hole this tool exists to avoid opening.

    If ``register(role="admin")`` were ever reachable from the public route, the
    hub would hand out administrator accounts to anyone who could POST to it.
    The route passes ``role="researcher"`` explicitly; this pins the default it
    would fall back to.
    """
    from src.config import get_settings
    from src.license_service.db_schema import initialize_license_schema

    initialize_license_schema(get_settings().paths.licenses_db)
    result = _auth(hub_root).register("stranger@example.com", "correcthorse", "Lab")

    assert result["role"] == "researcher"
