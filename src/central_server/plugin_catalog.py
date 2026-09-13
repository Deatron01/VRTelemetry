# src/central_server/plugin_catalog.py
"""`CatalogEntry` and the one-time JSON-to-database seed for the plugin catalog.

Plugins live in external GitHub repositories (`plugins/registry.json` on a
workstation, once installed -- see `src.plugin_manager`). The catalog is the
operator-curated allowlist a workstation's `GET /api/plugins/catalog` route
(`src.interfaces.api.routers.plugins`) fetches from this hub and shows in the
researcher's "Install a plugin" UI: which repositories are vetted, what they
do, and where to clone them from -- so a researcher never has to paste a git
URL from Slack into `registry.json` by hand.

**As of VRT-29's admin-CRUD follow-up, the live catalog is the
`plugin_catalog` table in `central_data.db`** (`data_schema.py`'s
`plugin_catalog` table, managed through `CentralDataManager.list_plugins`/
`add_plugin`/`update_plugin`/`set_plugin_published`/`delete_plugin` and the
admin dashboard's Plugin Catalog tab, `/admin/plugins/*`) -- not this file.
`plugin_catalog.json` and `load_catalog()` below now exist only as the
one-time seed `data_schema.seed_plugin_catalog_from_json` migrates into that
table the first time it's ever empty; editing the JSON file after that point
does nothing; it's history, not configuration. This was a deliberate,
short-lived step (a JSON file was the right size for a single operator
before an admin UI existed for it), not a mistake being corrected.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: Colocated with this module rather than under a configurable data root:
#: the catalog ships with the hub's own code (it names which repositories
#: *this deployment's operator* has vetted), the same way
#: `src/central_server/admin_ui/` ships as static files rather than living
#: under `PathSettings.data_root`.
DEFAULT_CATALOG_PATH = Path(__file__).parent / "plugin_catalog.json"

_REQUIRED_STRING_FIELDS = ("plugin_id", "name", "description", "repo_url")


@dataclass(frozen=True)
class CatalogEntry:
    """One approved plugin, as `GET /api/plugins/catalog` returns it."""

    plugin_id: str
    name: str
    description: str
    repo_url: str
    #: git ref to install from a workstation's `POST /api/plugins/install`.
    ref: str = "main"
    homepage: str | None = None
    maintainer: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "description": self.description,
            "repo_url": self.repo_url,
            "ref": self.ref,
            "homepage": self.homepage,
            "maintainer": self.maintainer,
        }


def load_catalog(catalog_path: Path = DEFAULT_CATALOG_PATH) -> list[CatalogEntry]:
    """Read and parse the plugin catalog.

    A malformed entry is logged and skipped rather than failing the whole
    route -- one bad entry must not take the rest of the catalog down with
    it, matching `src.plugin_manager.manager.load_registry`'s own posture on
    its side of the same list. Returns an empty list, rather than raising,
    if the file is missing.
    """
    if not catalog_path.exists():
        logger.warning(
            f"No plugin catalog at {catalog_path}; the catalog route will report zero plugins."
        )
        return []

    try:
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.error(f"Could not read plugin catalog {catalog_path}: {exc}")
        return []

    entries: list[CatalogEntry] = []
    for item in raw.get("plugins", []):
        if not isinstance(item, dict):
            continue
        missing = [field_name for field_name in _REQUIRED_STRING_FIELDS if not item.get(field_name)]
        if missing:
            logger.error(f"Skipping malformed catalog entry {item!r}: missing {', '.join(missing)}")
            continue
        entries.append(
            CatalogEntry(
                plugin_id=item["plugin_id"],
                name=item["name"],
                description=item["description"],
                repo_url=item["repo_url"],
                ref=item.get("ref", "main"),
                homepage=item.get("homepage"),
                maintainer=item.get("maintainer"),
            )
        )
    return entries
