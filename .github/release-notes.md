## Downloads

| File | Use it on |
|---|---|
| `VRTelemetry-Setup-<version>.exe` | **Recording workstation (Windows)** — the desktop app with its backend bundled. No Python needed. |
| `VRTelemetry-Hub-Setup-<version>.exe` | **Hub (central server, Windows)** — no Python needed. Asks for the hub's LAN address, then creates the TLS certificate, opens the firewall port, starts the hub with Windows and offers to create the first administrator. Leaves a *workstation kit* to copy to each recording PC. |
| `VRTelemetry-<version>-x86_64.AppImage` | Recording workstation or analysis machine on Linux. |
| `vrtelemetry-<version>-py3-none-any.whl` | Hub on Linux — `pip install "vrtelemetry-<version>-py3-none-any.whl[server]"`, then follow README §04. |
| `vrtelemetry-<version>.tar.gz` | Source distribution. |
| `SHA256SUMS.txt` | Checksums — verify your download before installing. |

## Before you install

- The Windows installer shows the licence and research-use disclaimer and asks
  you to accept them.
- **The builds are not code-signed yet.** Windows SmartScreen may warn about an
  unrecognised app; choose *More info → Run anyway* only if the checksum matches
  `SHA256SUMS.txt` and you downloaded it from this page.
- The workstation API listens on `127.0.0.1:8000` with no authentication by
  design. Do not expose it to a network — see SECURITY.md.
- Set up the hub first (TLS certificate, first administrator, licence keys),
  then point each workstation at it — README §04–§06. With the Windows hub
  installer that is: install, create the administrator, issue keys, and copy
  the workstation kit into `%APPDATA%\VRTelemetry\data` on each recording PC.
- The desktop app keeps its data in `%APPDATA%\VRTelemetry\data` since 1.1.0.
  Earlier versions wrote it inside the install directory: before upgrading a
  1.0.0 install, copy `Sessions`, `AppData`, `LicenseServer`, `Logs` and any
  `config.toml` from `<install dir>\resources\backend` to that folder.
