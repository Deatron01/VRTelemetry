# Security Policy

VRTelemetry handles recordings of people, so security reports are taken
seriously.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Use GitHub's private reporting instead: on this repository, open the
**Security** tab and choose **Report a vulnerability**. Include what you found,
how to reproduce it, and which version or commit you tested.

You can expect an acknowledgement within a week. Please give a reasonable
window for a fix before disclosing publicly.

**Never include real participant data** — recordings, Parquet files, database
files, screenshots of patient records — in a report. Synthetic data reproduces
the same bugs.

## Supported versions

Only the latest release receives fixes.

## Deployment notes that matter for security

These are by design, and worth knowing before you deploy:

- **The workstation API (`127.0.0.1:8000`) has no authentication.** It serves
  participant records and starts recordings, and is meant to be reachable only
  from the same machine. Do not bind it to a network interface or put it behind
  a reverse proxy.
- **The hub refuses plain HTTP on the network.** Generate a certificate with
  `tools/generate_hub_certificate.py`; keep `hub-key.pem` private.
  `hub.allow_insecure_http` is for disposable test setups only.
- **The `quest_udp` backend accepts unauthenticated datagrams** from anyone on
  the network and is disabled unless explicitly enabled. Use it only on an
  isolated network.
- **Plugins run as separate processes with your user's privileges.** Install
  only plugins you trust.
- **Release builds are not code-signed yet.** Download them only from this
  repository's Releases page and check the published SHA-256 checksums.
