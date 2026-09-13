# src/plugin_manager/manifest.py
"""The `plugin.json` contract every plugin repository must satisfy.

Part of the "Flawless Setup" standard: `PluginManager` refuses to provision
a plugin with no manifest, or one that fails validation, rather than
discovering a typo'd entrypoint or a protocol mismatch only once the process
has already been cloned, venv'd and launched. See
`plugins/PLUGIN_DEVELOPER_GUIDE.md` for the full spec plugin authors must
follow, and `plugins/PROTOCOL.md` for what `protocol_version` governs.

Applies to every plugin regardless of source (git or local): the manifest is
what makes a plugin's own identity, description and entrypoint discoverable
by `PluginManager`, the catalog UI and an operator reading `registry.json`
alike, instead of being scattered across `registry.json` entries, a README
a human has to open, and whatever `app.py` happens to do.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.core.plugin_protocol import PROTOCOL_VERSION

#: Required top-level string fields. `entrypoint` and `protocol_version` are
#: validated separately below because they aren't plain strings.
_REQUIRED_STRING_FIELDS = ("plugin_id", "name", "version", "description")


class PluginManifestError(RuntimeError):
    """`plugin.json` is missing, malformed, or fails validation.

    Raised by :func:`load_manifest`. Callers (`PluginManager._start_one`)
    catch this exactly like `PluginGitError`/`PluginEnvironmentError`: logged
    and skipped, one plugin's bad manifest never stops the others or the
    Core Hub itself from starting.
    """


@dataclass(frozen=True)
class PluginManifest:
    """The validated contents of one plugin's `plugin.json`."""

    plugin_id: str
    name: str
    version: str
    description: str
    entrypoint: list[str]
    requirements_file: str
    protocol_version: int
    author: str | None
    homepage: str | None


def load_manifest(plugin_dir: Path) -> PluginManifest:
    """Read and validate `plugin_dir/plugin.json`.

    Args:
        plugin_dir: The plugin's checkout (git-sourced) or development
            directory (local-sourced) -- whatever `PluginManager` already
            resolved before calling this.

    Returns:
        The validated manifest.

    Raises:
        PluginManifestError: the file is missing, isn't valid JSON, is
            missing a required field, declares a malformed `entrypoint`, or
            declares a `protocol_version` this Core Hub's Event Router
            doesn't speak (see `src.core.plugin_protocol.PROTOCOL_VERSION`).
    """
    manifest_path = plugin_dir / "plugin.json"
    if not manifest_path.exists():
        raise PluginManifestError(
            f"{plugin_dir} has no plugin.json. Every plugin repository must carry one -- "
            f"see plugins/PLUGIN_DEVELOPER_GUIDE.md for the required shape."
        )

    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PluginManifestError(f"{manifest_path} is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise PluginManifestError(f"{manifest_path} must contain a JSON object.")

    missing = [field_name for field_name in _REQUIRED_STRING_FIELDS if not raw.get(field_name)]
    if missing:
        raise PluginManifestError(
            f"{manifest_path} is missing required field(s): {', '.join(missing)}. "
            f"See plugins/PLUGIN_DEVELOPER_GUIDE.md."
        )

    entrypoint = raw.get("entrypoint", ["python", "app.py"])
    if (
        not isinstance(entrypoint, list)
        or not entrypoint
        or not all(isinstance(token, str) for token in entrypoint)
    ):
        raise PluginManifestError(
            f"{manifest_path}: 'entrypoint' must be a non-empty list of strings, got {entrypoint!r}."
        )

    protocol_version = raw.get("protocol_version")
    if not isinstance(protocol_version, int) or isinstance(protocol_version, bool):
        raise PluginManifestError(
            f"{manifest_path}: 'protocol_version' (an integer) is required -- currently "
            f"{PROTOCOL_VERSION} for this Core Hub. See plugins/PROTOCOL.md."
        )
    if protocol_version != PROTOCOL_VERSION:
        raise PluginManifestError(
            f"{manifest_path} declares protocol_version={protocol_version}, but this Core "
            f"Hub's Event Router speaks protocol_version={PROTOCOL_VERSION}. See "
            f"plugins/PROTOCOL.md before changing either side."
        )

    return PluginManifest(
        plugin_id=str(raw["plugin_id"]),
        name=str(raw["name"]),
        version=str(raw["version"]),
        description=str(raw["description"]),
        entrypoint=entrypoint,
        requirements_file=str(raw.get("requirements_file", "requirements.txt")),
        protocol_version=protocol_version,
        author=raw.get("author"),
        homepage=raw.get("homepage"),
    )
