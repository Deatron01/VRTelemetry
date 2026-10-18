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

import re
import shutil
import sys
from pathlib import Path
from typing import Any

from src.central_server.cli import FROZEN_DEFAULT_DATA_ROOT, KIT_DIR_NAME
from src.config import CentralServerSettings
from src.storage.hub_address import is_configured
from src.utils.logger import logger

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on the 3.10 leg of the CI matrix
    import tomli as tomllib

#: Where the hub installer leaves the kit. Looked up at call time, so a test
#: can point it elsewhere.
DEFAULT_KIT_DIR = FROZEN_DEFAULT_DATA_ROOT / KIT_DIR_NAME

#: The kit's own name for the CA file, and the name the copy keeps. The kit's
#: ``config.toml`` refers to it relatively, which resolves against the data root
#: because that is the backend's working directory.
CA_FILE_NAME = "hub-ca.pem"

_CENTRAL_HEADER = re.compile(r"^[ \t]*\[[ \t]*central[ \t]*\][ \t]*(#.*)?$", re.MULTILINE)


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

    config_path = config_dir / "config.toml"
    try:
        existing = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
        merged = _merge_central_block(existing, kit_url)
        if merged is None:
            logger.info(
                f"Hub kit at {kit_dir} not adopted: {config_path} defines [central] in a "
                "form this cannot extend safely; copy the kit's two settings in by hand"
            )
            return None
        shutil.copyfile(kit_ca, config_dir / CA_FILE_NAME)
        config_path.write_text(merged, encoding="utf-8")
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
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


def _merge_central_block(existing: str, url: str) -> str | None:
    """``existing`` config text with the kit's two ``[central]`` keys added.

    Returns ``None`` when the file defines ``central`` without a ``[central]``
    header to insert under (dotted keys, an inline table): writing a second
    header would make the file invalid TOML, and the backend refuses to start
    on an invalid config. The result is parsed before it is returned, so a
    merge can only ever produce a file the backend will read.
    """
    lines = f'url = "{url}"\nca_bundle = "{CA_FILE_NAME}"\n'
    parsed = tomllib.loads(existing)
    if existing and not existing.endswith("\n"):
        existing += "\n"
    if "central" not in parsed:
        separator = "\n" if existing else ""
        merged = f"{existing}{separator}# Adopted from this machine's hub kit.\n[central]\n{lines}"
    else:
        header = _CENTRAL_HEADER.search(existing)
        if header is None:
            return None
        insert_at = existing.index("\n", header.end()) + 1
        merged = existing[:insert_at] + lines + existing[insert_at:]

    central = tomllib.loads(merged).get("central", {})
    if central.get("url") != url or central.get("ca_bundle") != CA_FILE_NAME:
        return None
    return merged
