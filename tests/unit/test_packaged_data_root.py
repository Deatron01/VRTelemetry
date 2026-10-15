"""The packaged desktop app keeps its data outside the install directory.

The frozen backend's data root defaults to its working directory, and
electron/backend-manager.js used to start it in ``resources/backend``. Under
Program Files that made recording impossible, and anywhere else an upgrade or
uninstall -- which replaces ``resources/`` -- deleted every session, the patient
database and the licence activation along with the program.

Electron cannot be run here, so this pins the source, the same way
``test_cors_policy`` pins ``electron/main.js``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _code(relative: str) -> str:
    source = (REPO_ROOT / relative).read_text(encoding="utf-8")
    return "\n".join(line for line in source.splitlines() if not line.strip().startswith("//"))


def test_the_packaged_backend_does_not_run_in_the_install_directory() -> None:
    code = _code("electron/backend-manager.js")

    assert "cwd: path.dirname(exePath)" not in code, (
        "the frozen backend runs in resources/backend, so its data lives in the "
        "install directory and an upgrade deletes it"
    )
    assert "cwd: dataRoot" in code


def test_the_data_root_is_user_data_unless_the_lab_set_one() -> None:
    code = _code("electron/backend-manager.js")

    assert re.search(r"process\.env\.VRT_PATHS__DATA_ROOT\s*\|\|", code), (
        "an explicit VRT_PATHS__DATA_ROOT must still win"
    )
    assert "app.getPath('userData')" in code
    assert "VRT_PATHS__DATA_ROOT: dataRoot" in code, (
        "the backend must be told the root, not only started in it"
    )


def test_user_data_is_named_after_the_product() -> None:
    r"""``app.getPath('userData')`` is named from package.json's top-level
    ``productName`` (else ``name``) -- not from ``build.productName``. Without it
    the data root was ``%APPDATA%\vrtelemetry-desktop\data``, not the
    ``%APPDATA%\VRTelemetry\data`` the README and the hub's workstation kit
    tell people to copy into.
    """
    import json

    package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))

    assert package.get("productName") == "VRTelemetry"
