# Installers for the workstation and the hub — design

**Date:** 2026-10-15
**Status:** approved in conversation, implementing
**Release target:** `v1.1.0`

## Why

A build is needed that installs *completely* on the lab's Windows machines: the
desktop client on the recording PC, and the hub on the server. It has to be
ready before next week's test day with participants, where the software records
everything it can today (eye tracking, pose, hardware state, biosensors, A/V).

What exists today (`v1.0.0`, built by `.github/workflows/release.yml`):

| Piece | State |
|---|---|
| Client installer (`VRTelemetry-Setup-<v>.exe`, NSIS via electron-builder) | Exists. Has a data-loss bug, see below. |
| Hub | Only a wheel. Needs Python, `pip`, a hand-run certificate script and a hand-run admin bootstrap. Not an installer. |
| Current code | ~3,300 lines of uncommitted work (biosensor ingest, live biometrics, desktop mirror, synced session video) are not in `v1.0.0`. |

## Success criteria

1. On a Windows machine with no Python or Node, running
   `VRTelemetry-Hub-Setup-1.1.0.exe` leaves a hub that answers
   `https://<ip>:9000/health` with `"service": "vrtelemetry-hub"`, survives a
   reboot, and is reachable from the LAN through the firewall.
2. The administrator can create the first admin account from a Start-menu entry,
   without a command line or Python.
3. Running `VRTelemetry-Setup-1.1.0.exe` on the recording PC, then copying the
   hub's *workstation kit* into the client's data folder, is enough to activate
   a licence, record a session and see it upload.
4. Upgrading or uninstalling the client does not delete recorded sessions,
   patients or the licence activation.
5. Both installers are attached to a `v1.1.0` GitHub release with checksums,
   and copies sit in the local, git-ignored `release/` folder.

## 0. Code state

- Commit the staged code (not `doc/KozlovszkyMiklos/`, not `Claude outputs/_tmp/`:
  the repository is being prepared for public visibility and those are
  internal), then rebase onto `origin/main` (3 commits; `pyproject.toml` and
  `Export.tsx` overlap).
- Gates must pass before anything is built: `ruff check`, `ruff format --check`,
  `mypy`, `pytest -m "not hardware"`, `tools/check_repo_hygiene.py`, frontend
  build.
- Version goes to `1.1.0` in `pyproject.toml` and `package.json` (the release
  workflow checks both against the tag).

## 1. Client: data outside the install directory

**Bug.** `electron/backend-manager.js` spawns the frozen backend with
`cwd = resources/backend`, and `PathSettings.data_root` defaults to the current
directory. So the packaged app writes sessions, `patients.db`, the licence cache
and `config.toml` *inside the install directory*:

- installed under `Program Files` (the installer offers it), recording cannot
  write at all without elevation;
- upgrading or uninstalling replaces `resources/`, deleting every recording.

**Fix.** When packaged, the Electron shell creates
`%APPDATA%\VRTelemetry\data` (`app.getPath('userData')` + `data`, apart from
Chromium's own files), passes it as `VRT_PATHS__DATA_ROOT`, **and starts the
backend in it** — `get_settings()` reads `config.toml` from the working
directory, and a relative `central.ca_bundle` resolves against it. Development mode is unchanged
(`npm run dev` keeps the repository root). An explicitly set
`VRT_PATHS__DATA_ROOT` in the environment still wins, so a lab can point it at
another disk.

Per-user rather than `%ProgramData%`: a folder a standard user creates under
`ProgramData` is read-only to every other account, which breaks the second
researcher who logs in. The recording PC is a single-account machine in
practice; per-user is the default that cannot break.

## 2. Hub installer

### 2a. Frozen hub executable

`build/hub.spec` (PyInstaller, onedir) freezes a new entry point
`src/central_server/cli.py` into `vrtelemetry-hub.exe`, with subcommands:

| Command | Does |
|---|---|
| `vrtelemetry-hub serve` (default) | Runs the hub exactly as `vrtelemetry-hub` does today. |
| `vrtelemetry-hub gen-cert --host <ip> [--host ...]` | `tools/generate_hub_certificate.py`, moved into the package so it is frozen with it. The tool keeps working from `tools/` as a thin wrapper. |
| `vrtelemetry-hub bootstrap-admin --email ...` | `src.license_service.bootstrap_admin.main`. |

The data root is not the working directory: the installer writes
`VRT_PATHS__DATA_ROOT` into the scheduled task's environment via a launcher
(below). The executable itself also accepts `--data-root` so the Start-menu
entries can pass it explicitly.

`server.py` performs schema initialisation at import, which is acceptable for a
process entry point; the CLI imports it only inside `serve`, so `gen-cert` and
`bootstrap-admin` do not start logging or create databases as a side effect
they do not need.

### 2b. NSIS installer — `build/hub-installer.nsi`

Per-machine, requires administrator. Pages:

1. Licence (`LICENSE` + `DISCLAIMER.md`, same generated text as the client).
2. Install directory (default `C:\Program Files\VRTelemetry Hub`).
3. **Network:** hub LAN address (pre-filled with the first non-loopback IPv4
   address) and port (default 9000).

On install:

- Copy the frozen hub to the install directory.
- Data root `C:\ProgramData\VRTelemetryHub` (created; ACL limited to
  Administrators and SYSTEM, since it holds participant data and the CA key).
- Write `config.toml` there with `[hub] host = "0.0.0.0"`, the port, and
  `tls_certfile` / `tls_keyfile` — **only if no `config.toml` exists**, so an
  upgrade keeps the lab's edits.
- Run `gen-cert --host <ip>` — only if no certificate exists.
- Build the **workstation kit** at `C:\ProgramData\VRTelemetryHub\workstation-kit\`:
  `hub-ca.pem`, a `config.toml` with `[central] url = "https://<ip>:<port>"`
  and `ca_bundle` pointing at the kit's CA in the client's data folder, and a
  `README.txt` with the two copy steps.
- Firewall: inbound TCP rule for the port, program-scoped to the hub exe.
- Scheduled task `VRTelemetry Hub`: at system start-up, as SYSTEM, restart on
  failure every minute, no execution time limit. Started immediately.
- Start menu: *Create first administrator* (console, prompts for email and
  password), *Open admin UI*, *Open workstation kit folder*, *Hub logs*.

On uninstall: stop and delete the task, remove the firewall rule, remove program
files. **Data in `ProgramData` stays**; the uninstaller says where it is.

Rejected alternatives:

- *Windows service via WinSW/NSSM:* proper service semantics, but adds a
  third-party binary to a medical-research deployment for no capability the
  scheduled task lacks here.
- *ZIP + PowerShell script:* fastest, but it is not the installer that was asked
  for and depends on the execution policy of the target machine.

### 2c. Toolchain

`makensis` from NSIS 3. CI: preinstalled on GitHub's Windows runners (verified
in the workflow run, falls back to `choco install nsis`). Locally: the NSIS copy
electron-builder downloads into its cache, or an installed NSIS.

## 3. Release

- `release.yml` gains a `hub-windows` job: PyInstaller `build/hub.spec`,
  smoke-test the frozen hub (start on loopback without TLS, wait for `/health`,
  check `service`), then `makensis`. Its artefact joins the release with the
  others and goes into `SHA256SUMS.txt`.
- Release notes: the hub row points at the hub installer; the wheel stays for
  Linux hubs.
- Local copies in `release/` (git-ignored). Binaries are never committed.

## 4. Verification

- Unit tests: the Electron data-root choice is not unit-testable here; the hub
  CLI argument routing and the workstation-kit `config.toml` content are.
- Local end-to-end on this machine: install the hub, `/health` over TLS with the
  CA, create the admin, issue a licence; install the client, copy the kit,
  activate, record (hardware permitting) or at least start a session, confirm
  sync status; uninstall the client, confirm data survives; reinstall.
- If Windows Sandbox is available, repeat the installs there for a clean-machine
  check (no Python, no Node, no VC++ runtime assumptions).

## Out of scope

- The test-day protocol and the evaluation of its data (separate piece of work).
- Code signing (SmartScreen will warn, as it does for `v1.0.0`).
- A Linux hub package.
