# Plugin 01 -- medical/psychometric analytics

> Protocol/wire format is specified once, for every plugin, in
> [`../PROTOCOL.md`](../PROTOCOL.md) -- read that first if you're modifying
> this plugin's Hub-facing code or writing a new plugin from scratch. This
> file covers what's specific to this one.

Out-of-process subscriber to the Core Hub's Event Router
(`/ws/hub/telemetry`). Computes SSQ and NASA-TLX questionnaire scores and a
per-session biometric summary, and writes both to `output/` as JSON.

**Does not enforce GDPR consent.** That stays in the Core Hub
(`src/patients/`, `src/application/consent.py`), unchanged, because this
plugin only learns about a session after `POST /api/recording/start` has
already decided to record it -- see the top of `app.py` and the plan doc's
"Why consent enforcement cannot become a plugin."

**Does not compute a stress/arousal score.** `stress_inference.py` raises
unconditionally, matching `src/av_recording/stress_score.py`'s
`StressScorer` in the Core Hub, pending the EU AI Act Art. 5(1)(f) legal
opinion referenced there.

## Running

Provisioned automatically by `PluginManager` when `registry.json` lists this
plugin with `"enabled": true` (it is, by default). To run by hand for
development:

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
set HUB_WS_URL=ws://127.0.0.1:8000/ws/hub/telemetry
.venv\Scripts\python app.py
```

## Environment variables

| Variable | Set by | Meaning |
|---|---|---|
| `HUB_WS_URL` | `PluginManager` | The Event Router's WebSocket URL. |
| `HUB_PLUGIN_TOKEN` | `PluginManager`, if configured | Shared token for `EventRouter(shared_token=...)`. |
| `PLUGIN_OUTPUT_DIR` | operator (optional) | Where JSON output is written. Defaults to `./output`. |

## Event contract

Consumes, from `/ws/hub/telemetry`:

- `{"type": "session_start", "session_id": ..., "consent_id": ...}`
- `{"type": "telemetry_frame", "session_id": ..., "frame": {...}}` -- `frame`
  keys match `TelemetryFrame`'s field names (`src/core/datatypes.py`).
- `{"type": "session_stop", "session_id": ...}`
- `{"type": "questionnaire_submitted", "session_id": ..., "instrument": "ssq"|"nasa_tlx", "items": {...}}`
  -- **not yet published by the Core Hub**; see the plan doc's "Wiring
  questionnaires.py to the plugin" for the one route change that would add
  this.

Produces nothing back onto the WebSocket in this version (v1 is
one-directional: Hub -> plugin). `output/<session_id>_biometric_summary.json`
and `output/<session_id>_<instrument>.json` are this plugin's only outputs.
