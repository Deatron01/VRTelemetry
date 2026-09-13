# Writing a VR Telemetry Hub plugin: the "Flawless Setup" standard

This is the contract a plugin repository must satisfy so `PluginManager`
(`src/plugin_manager/`) can clone it, provision it, and run it without an
operator opening your code first. Read `plugins/PROTOCOL.md` first if you
haven't -- it's the wire protocol (what your plugin receives over
`/ws/hub/telemetry`); this document is the *packaging* contract (what your
repository must look like for the Hub to run it at all). The two are
independent: a plugin can satisfy this document and still be a bad protocol
citizen, or vice versa. You need both.

## Why this exists

Before this standard, `PluginManager` trusted `registry.json` for a
plugin's entrypoint and dependencies, which meant an operator had to already
know a plugin's internals (which file to run, what it needs installed)
before writing the entry that runs it. That doesn't scale past plugins the
operator wrote themselves, and it means a typo in `registry.json` --
`"entrypoint": ["python", "main.py"]` for a plugin whose file is `app.py` --
fails at process-spawn time with a bare "file not found" and no indication
of whose fault it is.

The fix: a plugin repository describes itself. `plugin.json` at the
repository root is the one file `PluginManager` reads to know how to run
your plugin, and it is validated -- structurally and against the Hub's own
`protocol_version` -- before your code is ever cloned into a venv or
spawned. A plugin that fails validation is refused with a specific,
actionable error (`PluginManifestError`, logged with your `plugin_id` and
the exact problem), not a stack trace three layers down in
`subprocess.Popen`.

## The required layout

```
your-plugin/
├── plugin.json          # required -- see below
├── README.md            # required -- see the template below
├── requirements.txt     # required if you have any dependency beyond stdlib
├── app.py                # or whatever plugin.json's entrypoint names
└── ...                   # anything else your plugin needs
```

## `plugin.json`

```json
{
  "plugin_id": "your-plugin-id",
  "name": "Human-Readable Plugin Name",
  "version": "0.1.0",
  "description": "One or two sentences: what this plugin does, and anything a researcher deciding whether to install it needs to know up front (does it enforce anything, does it need external software, does it write files).",
  "entrypoint": ["python", "app.py"],
  "requirements_file": "requirements.txt",
  "protocol_version": 1,
  "author": "Your name or team",
  "homepage": "https://github.com/your-org/your-plugin"
}
```

| Field | Required | Meaning |
|---|---|---|
| `plugin_id` | yes | Stable identifier, matches the `plugin_id` your `registry.json` entry (or the catalog) uses. `PluginManager` refuses to start a plugin whose manifest `plugin_id` doesn't match the registry entry pointing at it -- this catches "cloned the wrong repo into this slot" immediately instead of silently running the wrong code under the right name. |
| `name` | yes | Shown in the researcher-facing catalog and status UI (`GET /api/plugins/status`, `GET /api/plugins/catalog`). |
| `version` | yes | Your own version string. Not currently compared to anything -- it's for a human reading the status UI to know whether an install is current. |
| `description` | yes | Shown in the catalog. Say what your plugin does *and* what it doesn't (see `plugins/medical-plugin-01/plugin.json` for the pattern: "does not enforce GDPR consent, does not compute a stress score" is as load-bearing as what it does do). |
| `entrypoint` | no (default `["python", "app.py"]`) | Argv to launch your plugin. The literal token `"python"` is resolved to your plugin's own isolated venv interpreter -- never write an absolute path or rely on whatever `python` means on the operator's `PATH`. |
| `requirements_file` | no (default `requirements.txt`) | Relative to your plugin's own directory. `PluginManager` skips the install step entirely if this file doesn't exist -- a zero-dependency plugin needs no `requirements.txt` at all. |
| `protocol_version` | yes | Must equal the Hub's own `protocol_version` (currently **1** -- `src/core/plugin_protocol.py`). A mismatch is refused at start time with a message telling you which side is out of date, rather than your plugin connecting and silently misinterpreting messages. Bump this in your own manifest only when you've actually verified your plugin against the new protocol version -- see `plugins/PROTOCOL.md` §2 for what a version bump means. |
| `author` | no | Free text. |
| `homepage` | no | Free text (typically your repository URL, if different from where it's cloned from). |

**Validation is strict but forgiving of extra fields.** Unknown keys in
`plugin.json` are ignored, not rejected -- add whatever metadata your own
tooling wants; `PluginManager` only reads the fields above.

## `README.md` template

Every plugin's `README.md` should answer these, in this rough order --
`plugins/medical-plugin-01/README.md` and `plugins/ros-unity-bridge/README.md`
are both written to this template and are the reference to copy from:

```markdown
# <Plugin Name>

> Protocol/wire format is specified once, for every plugin, in
> [`../PROTOCOL.md`](../PROTOCOL.md) -- read that first if you're modifying
> this plugin's Hub-facing code or writing a new plugin from scratch. This
> file covers what's specific to this one.

<One paragraph: what this plugin does, and what it deliberately does NOT do
-- especially anything that sounds like it should (e.g. "does not enforce
consent," "does not compute X" if X is legally or ethically sensitive).>

## Prerequisites (if any beyond `requirements.txt`)

<Anything PluginManager's pip-based install can't provide -- a system
package, a separately-installed runtime (ROS 2, a hardware SDK), a service
that needs to be running (rosbridge_suite). Say explicitly what happens if
this plugin starts without them (fails fast? partially works?).>

## Running standalone (development)

    python -m venv .venv
    .venv\Scripts\pip install -r requirements.txt
    set HUB_WS_URL=ws://127.0.0.1:8000/ws/hub/telemetry
    .venv\Scripts\python app.py

## Environment variables

| Variable | Set by | Meaning |
|---|---|---|
| `HUB_WS_URL` | `PluginManager` | The Event Router's WebSocket URL. |
| `HUB_PLUGIN_TOKEN` | `PluginManager`, if configured | Shared token, if the Hub requires one. |
| `PLUGIN_ID` | `PluginManager` | Your own `plugin_id`, injected for logging. |
| *(yours)* | operator, via `registry.json`'s `env` | Anything plugin-specific. |

## Event contract

<Which message `type`s you consume (see PROTOCOL.md §3), which `frame`
fields you read, and what you produce -- output files, or nothing back onto
the WebSocket (v1 is Hub -> plugin only; see PROTOCOL.md §6, rule 6).>
```

## Getting into the approved catalog

The Central Server's catalog (`src/central_server/plugin_catalog.json`,
served at `GET /api/plugins/catalog`) is what lets a researcher install your
plugin by name from the Electron app's Plugins panel, instead of an operator
hand-editing `registry.json` on every workstation. Getting listed is
whatever process this deployment's operator runs (this repository doesn't
prescribe one -- it's a JSON file an operator edits deliberately; see
`plugin_catalog.py`'s docstring). What the operator needs from you to add an
entry is exactly your `plugin.json`'s `plugin_id`/`name`/`description` plus
your repository's clone URL and the `ref` to install -- nothing your
manifest doesn't already state.

## Checklist before you call a plugin done

- [ ] `plugin.json` at the repository root, with all required fields, and
      `protocol_version` matching `src/core/plugin_protocol.py`'s current
      value.
- [ ] `README.md` following the template above.
- [ ] `requirements.txt` if you depend on anything beyond stdlib -- pin
      versions; your dependencies install into your own isolated venv, never
      the Hub's, but an unpinned `requirements.txt` can still break on a
      future `pip install` if a dependency ships a breaking release.
- [ ] Ignores any message `type` it doesn't recognise (PROTOCOL.md §6,
      rule 1).
- [ ] Checks `protocol_version` on every received message, not just at
      connect time (rule 2).
- [ ] Never blocks the WebSocket read loop on slow per-frame work (rule 3).
- [ ] Reconnects with backoff and tolerates a `session_id` it never saw a
      `session_start` for (rule 4).
- [ ] Fails safe if it's down: recording must be verifiably unaffected by
      this plugin being absent, crashed, or never started (rule 5).
- [ ] Runs standalone per the README's instructions, from a clean clone,
      before you consider it ready for `PluginManager` to run it for you.
