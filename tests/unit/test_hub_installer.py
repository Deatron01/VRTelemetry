"""The hub installer replaces the program, not just overwrites it.

`File /r` adds and overwrites but never deletes, so upgrading 1.1.1 -> 1.1.2
left `_internal/vrtelemetry-1.1.1.dist-info` beside the new one, and the hub
went on reporting 1.1.1 -- any module a release drops would linger the same
way. makensis cannot run here, so this pins the script.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _install_section() -> str:
    script = (REPO_ROOT / "build/hub-installer.nsi").read_text(encoding="utf-8")
    start = script.index('Section "Hub"')
    return script[start : script.index("SectionEnd", start)]


def test_an_upgrade_removes_the_previous_bundle_before_copying() -> None:
    section = _install_section()
    cleared = section.find('RMDir /r "$INSTDIR\\_internal"')
    copied = section.find('File /r "${HUB_DIST}')

    assert cleared != -1, "the old _internal/ survives an upgrade"
    assert cleared < copied, "_internal/ must be cleared before the new bundle is copied"
    assert section.find("StopHub") < cleared, "the hub must be stopped before its files go"
