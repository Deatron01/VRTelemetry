# src/storage/local_hub_kit.py
"""Configure a workstation from the hub's kit when both run on one machine.

The hub's ``setup`` writes a *workstation kit* -- ``hub-ca.pem`` plus a
``config.toml`` naming the hub's address and that CA -- and the installer
leaves it in ``%ProgramData%\\VRTelemetryHub\\workstation-kit``, readable by
every user and writable only by Administrators. On a second PC someone has to
carry those files over. On the hub's own PC they are already here, so asking a
researcher to copy them from one folder to another was a setup step with no
decision in it.

So the backend adopts the kit at startup, under one rule: **only when nothing
else names a hub.** An address in ``config.toml`` or the environment, an
explicit ``ca_bundle``, or a different address the researcher saved in the app
each mean someone chose, and the kit never overrides a choice.

Trusting the kit's CA without asking is safe for the same reason it is safe to
read it at all: only an administrator of this machine could have written it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from src.central_server.cli import FROZEN_DEFAULT_DATA_ROOT, KIT_DIR_NAME
from src.config import CentralServerSettings
from src.config.workstation_kit import CA_FILE_NAME, KitMergeError, install_workstation_kit
from src.storage.hub_address import is_configured
from src.utils.logger import logger

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on the 3.10 leg of the CI matrix
    import tomli as tomllib

#: Where the hub installer leaves the kit. Looked up at call time, so a test
#: can point it elsewhere.
DEFAULT_KIT_DIR = FROZEN_DEFAULT_DATA_ROOT / KIT_DIR_NAME


def adopt_local_hub_kit(
    config_dir: Path,
    central: CentralServerSettings,
    *,
    saved_url: str | None,
    kit_dir: Path | None = None,
) -> str | None:
    """Copy this machine's hub kit into ``config_dir`` if no hub is chosen yet.

    Args:
        config_dir: Where the backend reads ``config.toml`` from -- its working
            directory, which the desktop app sets to the data root.
        central: The hub settings as resolved *before* adoption, from
            ``config.toml`` and the environment together.
        saved_url: The address the researcher saved in the app, if any. It
            outranks configuration at runtime, so it outranks the kit too --
            unless it is the kit's own address, in which case the kit supplies
            the CA that address needs.
        kit_dir: Defaults to :data:`DEFAULT_KIT_DIR`.

    Returns:
        The hub address now configured, or ``None`` if nothing was changed.
        Never raises: a workstation that cannot adopt the kit is merely
        unconfigured, which is a supported state.
    """
    if is_configured(central.url) or central.ca_bundle is not None:
        return None

    kit_dir = kit_dir if kit_dir is not None else DEFAULT_KIT_DIR
    kit_ca = kit_dir / CA_FILE_NAME
    kit_url = _kit_url(kit_dir / "config.toml")
    if kit_url is None or not kit_ca.is_file():
        return None

    if is_configured(saved_url) and (saved_url or "").strip().rstrip("/") != kit_url:
        logger.info(
            f"Hub kit at {kit_dir} not adopted: the researcher saved a different hub address"
        )
        return None

    # The writer pairing uses too (src.config.workstation_kit): ``hub-ca.pem``
    # beside ``config.toml``, ``[central]`` merged into an existing file, and
    # nothing written at all when that file cannot be extended safely (dotted
    # keys, an inline table, invalid TOML). The ``ca_bundle`` it writes is the
    # kit's relative ``hub-ca.pem``, which resolves against the data root
    # because that is the backend's working directory. The checks above are
    # what keep it from replacing a hub someone chose: the merge itself would.
    try:
        install_workstation_kit(config_dir, kit_url, kit_ca.read_bytes())
    except KitMergeError as exc:
        logger.info(
            f"Hub kit at {kit_dir} not adopted: {config_dir / 'config.toml'} cannot be "
            f"extended safely ({exc}); copy the kit's two settings in by hand"
        )
        return None
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        logger.warning(f"Hub kit at {kit_dir} not adopted: {exc}")
        return None

    logger.info(f"Adopted this machine's hub kit: uploads go to {kit_url}")
    return kit_url


def _kit_url(kit_config: Path) -> str | None:
    """The hub address the kit names, or ``None`` if it names none usably.

    The address is written back into TOML as a basic string, so anything that
    would need escaping is refused rather than escaped: the hub's own ``setup``
    never writes one, and a kit that has one was not written by it.
    """
    try:
        with kit_config.open("rb") as handle:
            central: Any = tomllib.load(handle).get("central", {})
    except (OSError, tomllib.TOMLDecodeError):
        return None
    url = central.get("url") if isinstance(central, dict) else None
    if not isinstance(url, str):
        return None
    url = url.strip().rstrip("/")
    if not url.startswith("https://") or any(c in url for c in '"\\\n\r'):
        return None
    return url
