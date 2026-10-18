"""What a workstation needs on disk to reach a hub: ``hub-ca.pem`` and ``[central]``.

Three things write this, and they must agree on the format:

* the hub's installer (``vrtelemetry-hub setup``), which leaves a *workstation
  kit* folder for an administrator to copy by hand;
* pairing (:mod:`src.infrastructure.hub_pairing`), where the workstation
  fetches the CA from a hub on another machine;
* a workstation on the hub's own machine adopting the local kit.

So the format lives here, with no third-party imports and nothing done at
import time, and both ends of the repository import it.

The difference between copying and installing is the existing ``config.toml``.
The kit README tells a person to "copy the [central] block into it instead" when
one is already there; a program has to do the same, because a workstation's
``config.toml`` may hold a consent configuration a lab spent an afternoon on.
:func:`merge_central_block` edits the ``[central]`` table line by line and leaves
every other line -- comments included -- exactly as it was.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on the 3.10 leg of the CI matrix
    import tomli as tomllib

#: The file name the CA certificate is written under, beside ``config.toml``.
CA_FILE_NAME = "hub-ca.pem"

#: Relative on purpose: the desktop app starts its backend in its data root, so
#: this resolves to the copy of ``hub-ca.pem`` placed beside ``config.toml``.
DEFAULT_CA_BUNDLE = CA_FILE_NAME

_TABLE_HEADER = re.compile(r"^\s*\[")
_CENTRAL_HEADER = re.compile(r"^\s*\[\s*central\s*\]\s*(#.*)?$")


def _toml_string(value: str) -> str:
    """``value`` as a TOML basic string."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def workstation_config_toml(url: str, ca_bundle: str = DEFAULT_CA_BUNDLE) -> str:
    """The ``config.toml`` a workstation needs to reach the hub at ``url``."""
    return (
        "# Copied from the VRTelemetry hub's workstation kit.\n"
        "[central]\n"
        f"url = {_toml_string(url)}\n"
        f"ca_bundle = {_toml_string(ca_bundle)}\n"
    )


class KitMergeError(ValueError):
    """An existing ``config.toml`` that cannot be merged into safely."""


def merge_central_block(existing: str, url: str, ca_bundle: str = DEFAULT_CA_BUNDLE) -> str:
    """``existing`` with ``central.url`` and ``central.ca_bundle`` set.

    Other keys in ``[central]`` (``timeout_sec``, ``allow_insecure_http``) and
    every other table are kept. A ``[central]`` table is appended when there is
    none.

    Args:
        existing: The current ``config.toml`` text.
        url: The hub address.
        ca_bundle: The value for ``central.ca_bundle``.

    Returns:
        The new text, checked to parse and to say what was asked.

    Raises:
        KitMergeError: if ``existing`` is not valid TOML, or spells the central
            settings in a form this line editor does not rewrite (an inline
            table or dotted keys). Refused rather than guessed at: the file is
            the lab's, not ours.
    """
    try:
        tomllib.loads(existing)
    except tomllib.TOMLDecodeError as exc:
        raise KitMergeError(f"the existing config.toml is not valid TOML: {exc}") from exc

    wanted = {"url": _toml_string(url), "ca_bundle": _toml_string(ca_bundle)}
    lines = existing.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"

    header = next((i for i, line in enumerate(lines) if _CENTRAL_HEADER.match(line)), None)
    if header is None:
        block = [f"{key} = {value}\n" for key, value in wanted.items()]
        prefix = "\n" if lines and lines[-1].strip() else ""
        merged = "".join(lines) + prefix + "[central]\n" + "".join(block)
    else:
        end = next(
            (i for i in range(header + 1, len(lines)) if _TABLE_HEADER.match(lines[i])),
            len(lines),
        )
        section = lines[header + 1 : end]
        for key, value in wanted.items():
            pattern = re.compile(rf"^\s*{key}\s*=")
            index = next((i for i, line in enumerate(section) if pattern.match(line)), None)
            if index is not None:
                section[index] = f"{key} = {value}\n"
                continue
            # After the last key line, so a blank line before the next table stays.
            last_key = max((i for i, line in enumerate(section) if "=" in line), default=-1)
            section.insert(last_key + 1, f"{key} = {value}\n")
        merged = "".join(lines[: header + 1] + section + lines[end:])

    try:
        central = tomllib.loads(merged).get("central", {})
    except tomllib.TOMLDecodeError as exc:
        raise KitMergeError(
            "the existing config.toml sets [central] in a form that cannot be merged "
            f"automatically ({exc}); add url and ca_bundle to it by hand"
        ) from exc
    if central.get("url") != url or central.get("ca_bundle") != ca_bundle:
        raise KitMergeError(
            "the existing config.toml sets [central] in a form that cannot be merged "
            "automatically; add url and ca_bundle to it by hand"
        )
    return merged


@dataclass(frozen=True)
class KitInstallResult:
    """What :func:`install_workstation_kit` wrote."""

    ca_path: Path
    config_path: Path
    #: True when an existing ``config.toml`` was merged into, False when created.
    merged: bool


def _write_atomically(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` so a crash leaves the old file or the new one."""
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as temp:
            temp.write(data)
        Path(temp_name).replace(path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def install_workstation_kit(
    data_root: Path, url: str, ca_pem: bytes | str, *, ca_bundle: str | None = None
) -> KitInstallResult:
    """Write ``hub-ca.pem`` and ``[central]`` into a workstation's data root.

    The new ``config.toml`` text is computed before anything is written, so a
    file that cannot be merged leaves both files untouched.

    Args:
        data_root: The workstation's data root (``%APPDATA%\\VRTelemetry\\data``
            in the packaged app).
        url: The hub address.
        ca_pem: The hub's CA certificate, PEM.
        ca_bundle: The value written as ``central.ca_bundle``; defaults to the
            relative ``hub-ca.pem``.

    Raises:
        KitMergeError: if an existing ``config.toml`` cannot be merged into.
        ValueError: if ``ca_pem`` holds no certificate.
    """
    pem = ca_pem.encode("ascii") if isinstance(ca_pem, str) else ca_pem
    if b"-----BEGIN CERTIFICATE-----" not in pem:
        raise ValueError("the hub CA is not a PEM certificate")

    data_root.mkdir(parents=True, exist_ok=True)
    ca_path = data_root / CA_FILE_NAME
    config_path = data_root / "config.toml"
    bundle = ca_bundle or DEFAULT_CA_BUNDLE

    merged = config_path.is_file()
    if merged:
        text = merge_central_block(config_path.read_text(encoding="utf-8"), url, bundle)
    else:
        text = workstation_config_toml(url, bundle)

    _write_atomically(ca_path, pem)
    _write_atomically(config_path, text.encode("utf-8"))
    return KitInstallResult(ca_path=ca_path, config_path=config_path, merged=merged)
