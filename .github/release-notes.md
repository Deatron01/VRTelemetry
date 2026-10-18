## Downloads

| File | Use it on |
|---|---|
| `VRTelemetry-Setup-<version>.exe` | **Recording workstation (Windows)** — the desktop app with its backend bundled. No Python needed. |
| `VRTelemetry-Hub-Setup-<version>.exe` | **Hub (central server, Windows)** — no Python needed. Asks for the hub's LAN address, then creates the TLS certificate, opens the firewall port, starts the hub with Windows and offers to create the first administrator. Recording PCs then pair with it by a one-time code. |
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
  installer that is: install, create the administrator, issue keys, then on
  each recording PC pair with the hub — **Generate code** under *Pair a
  Workstation* in the admin UI, **Connect to a hub on another machine…** in the
  desktop app. A desktop app installed on the hub's own PC configures itself.
- The desktop app keeps its data in `%APPDATA%\VRTelemetry\data` since 1.1.0.
  Earlier versions wrote it inside the install directory: before upgrading a
  1.0.0 install, copy `Sessions`, `AppData`, `LicenseServer`, `Logs` and any
  `config.toml` from `<install dir>\resources\backend` to that folder.
