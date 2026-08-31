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

## Quick start

Requires **Python 3.10+** and Node 20+ for the frontend.

```bash
pip install -e ".[dev]"
pytest -m "not hardware"          # 197 tests, no headset required
```

Run the backend the desktop shell talks to:

```bash
vrtelemetry-server                # or: uvicorn src.main:app --port 8000
```

Record from the command line, without the UI:

```bash
python -m src.interfaces.cli.record --backend openxr --gdpr-consent
```

The `hardware` marker separates tests that need a headset plugged in from the
ones that do not. CI runs `-m "not hardware"`; you should too, unless you have
one connected.

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

## Licence

Proprietary. All rights reserved.
