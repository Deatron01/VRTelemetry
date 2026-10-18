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
- **Pairing a workstation with the hub is authenticated by a short code.**
  Until a workstation holds the hub's CA certificate it cannot verify the hub,
  so the certificate is fetched over an unverified connection and authenticated
  by the six-digit code from the admin UI (*Pair a Workstation*). The code is
  not sent and is not an HMAC key an eavesdropper could brute-force offline:
  both sides run a password-authenticated key exchange (SPEKE over the
  2048-bit MODP group of RFC 3526, standard library only) and the hub's
  confirmation covers the CA's SHA-256 fingerprint, so a substituted
  certificate is rejected. Someone without the code gets one guess per
  exchange. The hub limits that: one active code at a time, valid for 10
  minutes and for one workstation, locked after 5 started exchanges, and at
  most 10 pairing requests per client address (60 in total) per minute.
  Nothing is written on the workstation unless the hub's confirmation
  verifies *and* a request verified against the received CA succeeds. Read
  the code to the researcher in person or by phone, and compare the
  fingerprint the app shows with the admin UI's if in doubt. The pairing
  routes (`/pairing/start`, `/pairing/finish`) are unauthenticated by
  necessity; `/admin/pairing/code` requires an admin session. See
  `src/infrastructure/hub_pairing.py` for the protocol and its rationale.
- **The `quest_udp` backend accepts unauthenticated datagrams** from anyone on
  the network and is disabled unless explicitly enabled. Use it only on an
  isolated network.
- **Plugins run as separate processes with your user's privileges.** Install
  only plugins you trust.
- **Release builds are not code-signed yet.** Download them only from this
  repository's Releases page and check the published SHA-256 checksums.
