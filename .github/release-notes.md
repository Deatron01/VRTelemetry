## Downloads

| File | Use it on |
|---|---|
| `VRTelemetry-Setup-<version>.exe` | **Recording workstation (Windows)** — the desktop app with its backend bundled. No Python needed. |
| `VRTelemetry-<version>-x86_64.AppImage` | Recording workstation or analysis machine on Linux. |
| `vrtelemetry-<version>-py3-none-any.whl` | **Hub (central server)** — `pip install "vrtelemetry-<version>-py3-none-any.whl[server]"`, then follow README §04. |
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
  then point each workstation at it — README §04–§06.
