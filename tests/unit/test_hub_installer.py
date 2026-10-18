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


def test_the_installer_registers_nothing_to_start_with_windows() -> None:
    """The hub starts when a person starts it.

    1.2.0 registered a boot-time scheduled task running as SYSTEM with restart
    on failure. Together with the firewall rule and ACL changes, an unsigned
    installer doing that is what Defender's ``Behavior:Win32/Persistence``
    heuristic looks for, and it removed the installer as malware.
    """
    script = (REPO_ROOT / "build/hub-installer.nsi").read_text(encoding="utf-8")

    assert "schtasks /Create" not in script
    assert "schtasks /Run" not in script
    assert "BootTrigger" not in script


def test_an_upgrade_removes_the_task_an_older_version_registered() -> None:
    """Otherwise a 1.2.0 install keeps starting the hub at boot after upgrading."""
    section = _install_section()

    assert 'schtasks /Delete /TN "${TASK_NAME}" /F' in section
    assert section.find("schtasks /Delete") < section.find('File /r "${HUB_DIST}')


def test_the_hub_is_started_from_a_shortcut_as_administrator() -> None:
    """The data directory is Administrators-only, so ``serve`` must be elevated."""
    section = _install_section()
    lnk = '"$DESKTOP\\${PRODUCT}.lnk"'

    assert f"CreateShortcut {lnk}" in section
    created = section.index(f"CreateShortcut {lnk}")
    # The shortcut's arguments follow on its continuation line.
    assert "serve" in section[created : created + 300]
    assert f"!insertmacro ShortcutRunAsAdmin {lnk}" in section
