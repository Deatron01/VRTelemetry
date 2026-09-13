# src/core/plugin_protocol.py
"""Single source of truth for the plugin wire-protocol version.

Both `src.interfaces.api.event_router` (which stamps this into every message
published to `/ws/hub/telemetry`) and `src.plugin_manager.manifest` (which
refuses to start a plugin whose `plugin.json` declares a different
`protocol_version`) need this number to agree by construction, not by two
people remembering to update two files in step.

It lives in `src.core` -- not in `src.interfaces.api.event_router`, where it
was first defined, and not in `src.plugin_manager` -- because it is a fact
about the wire format itself, independent of either side that speaks it, and
`src.core` is the one layer both the API layer and `plugin_manager` already
sit above in this codebase's dependency direction (outer imports inner,
never the reverse). See `plugins/PROTOCOL.md` for what the number actually
governs.
"""

from __future__ import annotations

#: Bump when the *shape* of a published message changes in a way a plugin
#: might need to branch on (a field renamed or removed, a new required
#: field, a changed frame column order). Adding a new event `type` or a new
#: optional field is not a breaking change and does not require a bump -- a
#: compliant plugin already ignores unknown `type`s and unknown fields (see
#: plugins/PROTOCOL.md, "Compatibility rules").
PROTOCOL_VERSION = 1
