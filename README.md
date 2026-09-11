# VRTelemetry

A research instrument for recording what happens to a person inside a VR
headset — eye tracking, pose, physiology, hardware state — and turning it into
data you can defend in a paper.

It is a desktop application a researcher runs at a workstation, plus a central
hub that collects sessions from every workstation in a lab. It records to
Parquet at the headset's sampling rate, links each session to a consented
patient record, scores the standard post-session questionnaires (SSQ, NASA-TLX),
and syncs to the hub when the network allows — queueing locally when it does not.

**Working offline is a supported state, not a failure mode.** A researcher with a
laptop in a room without the lab LAN can record a full session; everything
queues and drains when the hub comes back.

---

## What runs where

Three processes, separate on purpose:

| Component | What it is | Where it runs | Default address |
|---|---|---|---|
| **Hub** (central server) | Accounts, licences, the admin UI, and the archive every workstation uploads to. | One machine, always on. | `0.0.0.0:9000` |
| **Workstation API** | Acquisition, patient records, local storage, sync. | The PC with the headset. | `127.0.0.1:8000` |
| **Desktop app** | The Electron shell the researcher uses. Talks only to the workstation API on its own machine. | The same PC. | — |

The hub is the only component other machines talk to. The workstation API stays
on loopback: it serves patient records and starts recordings, and there is no
authentication in front of it because nothing outside the machine is meant to
reach it. Do not expose it.

---

## Install

**Python 3.10+**, and Node 20+ for the desktop app.

```bash
python -m venv venv
venv\Scripts\activate          # Windows;  source venv/bin/activate elsewhere
```

Then install the extra for the role that machine plays:

```bash
pip install -e ".[server]"       # hub machine — needs no VR bindings at all
pip install -e ".[workstation]"  # recording PC — pyarrow, pyopenxr, openvr, ...
pip install -e ".[dev]"          # contributor — workstation + tests + linters
```

Install the package rather than running from the source tree with
`requirements.txt`: the console commands below come from the install, and
`src/version.py` reads the version from package metadata.

LibOVR is deliberately not in `workstation` — it does not install everywhere.
Add `".[workstation,oculus]"` only if you record through it.

---

## 1. Start the hub and its admin UI

On the machine that will hold the archive, first create a TLS certificate for
the hub's LAN address. The hub carries participant data and eye-tracking
telemetry, so it refuses to listen on the network over plain HTTP (GDPR-01):

```bash
python tools/generate_hub_certificate.py --host <hub-ip>
```

It writes `hub-cert.pem`, `hub-key.pem` and `hub-ca.pem` to
`CentralServer/tls/` and prints the `config.toml` lines for the hub
(`[hub] tls_certfile` / `tls_keyfile`) and for each workstation
(`[central] ca_bundle`, pointing at a copy of `hub-ca.pem`). Then:

```bash
vrtelemetry-hub
```

It binds `0.0.0.0:9000` over HTTPS and logs the admin-UI and health URLs on
startup. Bound to `127.0.0.1` it may run without a certificate, for a
one-machine setup; `hub.allow_insecure_http = true` exists for disposable test
setups only.

**Create the first administrator — once, on the hub machine, before anyone
opens the admin UI:**

```bash
vrtelemetry-bootstrap-admin --email you@lab.org --org "Your Lab"
```

It prompts for a password. This step cannot be done through the web UI and is
not optional: `POST /auth/register` always creates a *researcher*, and promoting
anyone requires an admin session — so on a fresh install there is no way in.
Run the same command against an existing account later to promote it; it is
idempotent.

Then, in a browser:

| URL | What it is |
|---|---|
| `https://<hub-host>:9000/admin-ui/` | Admin dashboard — users, licences, active clients, sessions |
| `https://<hub-host>:9000/health` | Liveness. `{"ok": true, "service": "vrtelemetry-hub", ...}` |
| `https://<hub-host>:9000/docs` | Interactive API reference |

A browser warns about the certificate until `hub-ca.pem` is imported into its
trust store; the warning is about who issued the certificate, not about
encryption, which is in force either way.

Log in, then **Licenses → issue a key** for each researcher. A workstation
cannot record until it has activated with one.

To move the hub off port 9000, use a `[hub]` block in `config.toml` or:

```bash
VRT_HUB__HOST=0.0.0.0 VRT_HUB__PORT=9500 vrtelemetry-hub
```

**Two underscores** between `HUB` and `PORT`. The single-underscore spelling is
the pre-1.0 form; it is still honoured, but it logs a deprecation warning.

---

## 2. Start the workstation

### The desktop app, in development

From the repository root, once:

```bash
npm install
cd src/frontend/VRTelemetry && npm install && cd ../../..
```

Then, with your virtualenv activated:

```bash
npm run dev
```

That starts Vite on `http://localhost:5173` and the Electron shell against it.
The shell spawns the Python backend itself (`python -m uvicorn src.main:app` on
127.0.0.1:8000) and waits for the port before showing a window — so do not start
it separately. Activate the virtualenv first, so the `python` it spawns is the
one with the dependencies.

### The backend alone

For debugging, or a headless recording box:

```bash
vrtelemetry-server                # or: uvicorn src.main:app --port 8000
```

`http://127.0.0.1:8000/docs` is the API reference. `VRT_API__PORT` moves it —
but only for this command. The Electron shell hardcodes 8000 in
`electron/backend-manager.js` and does not read the setting, so if you are using
the desktop app, leave the port alone.

### Recording from the command line

```bash
vrtelemetry-record --consent-id <consent id> --backend steamvr
```

`--consent-id` is mandatory. It names a consent the participant gave on the
desktop app's consent screen, and the run refuses to start unless that consent
is on record, belongs to the configured study and wording, and has not been
withdrawn. The old `--gdpr-consent` flag is refused with an explanation: a flag
records only that someone typed it, not that the participant agreed (GDPR-09).
`--backend` takes `auto`, `steamvr`, `openxr`, `openxr_headless`, `oculus` or
`quest_udp`; `--port` sets the listening port under `quest_udp`. `quest_udp` is
refused unless `acquisition.enable_quest_udp = true`: its receiver accepts
unencrypted, unauthenticated datagrams from anyone on the network (GDPR-12).

### Packaging the desktop app

```bash
npm run package
```

Builds the frontend, freezes the backend with PyInstaller (`build/backend.spec`)
and produces an installer in `release/` — NSIS on Windows, DMG on macOS,
AppImage on Linux.

---

## 3. Point the workstation at the hub

Skip this only if both run on one machine with default ports.

1. **Open the port on the hub machine.** Windows Firewall blocks inbound 9000 by
   default. This is the most common reason a setup that works on one machine
   fails across two.
2. **Find the hub's LAN address** (`ipconfig`, or `ip addr`) and confirm it from
   the recording PC:
   ```bash
   curl --cacert hub-ca.pem https://<hub-ip>:9000/health
   ```
   Read the `service` field, not just the status code — a workstation pointed at
   some other service on the right port gets a reply and otherwise looks
   connected.
3. **Copy `hub-ca.pem` to the workstation** and set `ca_bundle` to it under
   `[central]` in the workstation's `config.toml`. Then, **in the desktop app**,
   on Live Acquisition, put `https://<hub-ip>:9000` into **Central Server
   Address** and press **Test**. A plain `http://` LAN address is refused. It reports the hub's name and
   version, or says exactly what went wrong. The address is saved on the
   machine — a one-time step, not per session.
4. **Register or log in, then activate** with a licence key from step 1.
5. Record. `GET /api/sync/status` reads 0 pending once a session has uploaded.

An unreachable hub is not an error state. Sessions record locally and queue; the
background scheduler drains them when the hub comes back.

---

## Testing it works

```bash
pytest -m "not hardware"          # 294 tests, no headset required
```

The `hardware` marker separates tests that need a headset from the ones that do
not. CI runs `-m "not hardware"`; so should you, unless one is connected.

---

## Clearing local data

Before a fresh study, or to reset a test machine:

```bash
python tools/reset_local_data.py --sessions            # dry run: prints what it would delete
python tools/reset_local_data.py --sessions --apply    # delete
```

Scopes: `--sessions`, `--hub`, `--patients`, `--activation`, `--licences`,
`--all`. Nothing happens without `--apply`, nothing outside the configured data
root is touched, and git-tracked files are refused. `--licences` wipes the
admin account too — you will bootstrap one again.

---

## Configuration

Nothing is hardcoded. Configuration is typed (`pydantic-settings`) and resolved
in one place, `src/config/settings.py`. Every path derives from a single data
root, so behaviour does not depend on which directory you launched from.

```bash
export VRT_PATHS__DATA_ROOT=/srv/vrtelemetry     # env, VRT_ prefix, __ nests
```

or copy `config.example.toml` to `config.toml` and edit it. Environment wins.

An unconfigured central server URL is **empty**, not a guessed default. That is
deliberate: a placeholder address makes an unconfigured install fail with a
connection error instead of saying it is unconfigured.

---

## Architecture

Layered, with dependencies pointing inward. Nothing in `domain/` knows that
FastAPI or SQLite exist.

```
src/
  domain/          Session profiles, anthropometrics, health profile mapping
  core/            TelemetryEngine, the acquisition loop, synchroniser
  backends/        OpenXR · SteamVR · Oculus · Quest-over-UDP · discovery
  analytics/       SSQ and NASA-TLX scoring
  infrastructure/
    persistence/   Connection policy, versioned migrations, repositories
  storage/         Parquet writer, uploaders, sync scheduler, heartbeat
  patients/        Patient registry and the GDPR consent lifecycle
  license_service/ Activation, offline grace, local cache
  interfaces/
    api/           create_app(), 8 routers / 29 routes, container, schemas
    cli/           The acquisition CLI
  central_server/  The hub: ingest, admin API, tenancy
  frontend/        React + Three.js analysis UI
electron/          Desktop shell
```

### The composition root

Every collaborator is built in exactly one place —
`src/interfaces/api/container.py` — and injected. **Importing a module performs
no I/O**, and there is a test that enforces it: `tests/unit/test_no_import_time_io.py`
imports every module under `src/` with `sqlite3.connect`, `open` and socket
`connect` guarded, and fails the build on any I/O attributable to our own code.

That constraint is what makes the rest testable. Two applications can coexist in
one process against separate data roots; a test injects a fake rather than
patching a name in a module namespace and hoping every caller reaches for it the
same way.

```python
from src.interfaces.api.app import create_app
from src.interfaces.api.container import build_container
from src.config import PathSettings, Settings

app = create_app(build_container(Settings(paths=PathSettings(data_root=tmp))))
app.dependency_overrides[dependencies.get_patients] = lambda: FakeRegistry()
```

### Storage

Four SQLite databases, all opened through one policy in
`infrastructure/persistence/connection.py`: WAL journalling, a 5-second busy
timeout, foreign keys on. There is a sync thread and a heartbeat thread writing
while the API reads; the defaults SQLite ships with are wrong for that.

Schema changes are **numbered, forward-only migrations** recorded in a
`schema_version` table. A failure raises. The previous idiom — `ALTER TABLE`
wrapped in `except sqlite3.OperationalError: pass` — cannot distinguish "already
applied" from "genuinely failed", and silently discarded every session's
metadata for three days before anyone noticed.

Telemetry frames go to Parquet, not SQLite. Metadata goes to SQLite, not Parquet.

---

## Data protection

The subjects are people, and the recordings are special-category health data.

- **Consent is enforced at the boundary.** Recording refuses to start for a
  patient whose consent was never given or has been withdrawn, and the
  questionnaire route applies the same rule — a session cannot accrue new health
  data against a patient who has since withdrawn.
- **Erasure is real.** Deleting a patient anonymises the local record and pushes
  the anonymised version to the hub, so the hub's copy reflects the erasure
  instead of keeping the pre-erasure PII forever.
- **PII never reaches the logs.** A redaction filter is installed on every sink.
- **Tenancy is derived from the authenticated account**, never from a client-
  supplied `license_id`.

---

## Development

The gates are not advisory. CI runs all of them.

```bash
ruff check && ruff format --check
mypy
pytest -m "not hardware"
python tools/check_repo_hygiene.py
pre-commit install
```

`pyproject.toml` holds a **per-file lint ratchet**. Every rule stays selected
globally, so new and newly-touched code is held to the full standard; the
`per-file-ignores` block records exactly which existing file violates which rule
today, each against the ticket that will remove it. Entries are deleted as
tickets land. Nothing is ever added without one.

Tests are organised by what they are for:

```
tests/unit/             Fast, isolated, no I/O beyond tmp_path
tests/integration/      Real applications, real databases, real lifespans
tests/characterisation/ Pins existing behaviour so it can be safely moved
tests/performance/      Throughput and zero-loss guarantees
```

**Characterisation tests describe what the code does today, bugs included.**
Where a route is wrong, the test says so in its docstring and names the ticket
that will change it. Nothing in that directory is an endorsement. When a ticket
lands and inverts one, the docstring explains why — that is the audit trail.

### Conventions

- Docstrings say *why*, not *what*. The code already says what.
- A comment that explains a non-obvious decision earns its place; one that
  narrates the next line does not.
- Refactors are proven mechanically, not asserted. Moving the API surface means
  generating the OpenAPI document before and after and diffing it.
- One ticket, one commit, with the reasoning in the message.

---

## Troubleshooting

**"Cannot reach central server" when activating.** The address is wrong, the hub
is not running, or the firewall is closed. The **Test** button beside the address
field distinguishes all three, including the case where something that is not a
hub answered.

**The admin UI rejects your login, or shows nothing.** That account is a
researcher, not an admin. Run `vrtelemetry-bootstrap-admin --email <that email>`
on the hub machine.

**Recording starts but no frames are written.** The headset is not reporting
valid tracking. Frames with no valid source are dropped rather than written as
all-zero rows; the teardown summary reports what actually reached disk, which is
the number to trust.

**Sessions record but never appear on the hub.** They are queued, not lost.
Check `/api/sync/status` on the workstation and `/health` on the hub.

**`pip install` fails on `openvr` or `pyopenxr`.** You are installing the
`workstation` extra on a machine with no VR runtime. The hub needs `[server]`,
which requires neither.

---

## Licence

Proprietary. All rights reserved.
