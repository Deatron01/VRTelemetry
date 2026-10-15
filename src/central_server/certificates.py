"""Create a TLS certificate for a VRTelemetry hub on a local network (GDPR-01).

The hub refuses to serve participant data over plain HTTP on a network
interface. A hub on a laboratory LAN rarely has a public DNS name, so a
certificate from a public authority is usually not an option. This tool
creates the next best thing: a small certificate authority that exists only for
this hub, and a server certificate signed by it for the hub's LAN address(es).

Workstations then trust *that CA only* for the hub -- ``central.ca_bundle`` --
so an attacker on the LAN cannot impersonate the hub without the CA's key.

Why a CA and not a single self-signed certificate: Python 3.13 and later verify
certificates in strict mode (``VERIFY_X509_STRICT``), which rejects a
self-signed leaf used as its own trust anchor because it lacks the extensions
a CA must carry. A two-level chain verifies on every supported version.

Usage::

    python tools/generate_hub_certificate.py --host 192.168.1.50
    python tools/generate_hub_certificate.py --host 192.168.1.50 --host hub.lab.local
    vrtelemetry-hub.exe gen-cert --host 192.168.1.50      # the installed hub

It lives in the package, not in ``tools/``, so the frozen hub carries it: the
hub installer runs it on a machine with no Python. ``tools/`` keeps a wrapper
at the old path, which the README, SECURITY.md and the hub's own error
messages name.

Writes to ``<data root>/CentralServer/tls/`` unless ``--out-dir`` is given:

    hub-ca.pem        copy to every workstation; set central.ca_bundle to it
    hub-ca-key.pem    keep offline; needed only to issue a new certificate
    hub-cert.pem      hub.tls_certfile
    hub-key.pem       hub.tls_keyfile -- private, stays on the hub

Requires ``cryptography`` (the hub's ``server`` extra).
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import ipaddress
import os
import sys
from pathlib import Path
from typing import Any

DEFAULT_DAYS = 825  # the longest validity current browsers accept for a leaf


def _write(path: Path, data: bytes, *, private: bool) -> None:
    path.write_bytes(data)
    if private and os.name == "posix":
        path.chmod(0o600)


def _san_entries(hosts: list[str]) -> list[Any]:
    from cryptography import x509

    entries: list[x509.GeneralName] = []
    for host in hosts:
        try:
            entries.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            entries.append(x509.DNSName(host))
    return entries


def generate(hosts: list[str], out_dir: Path, days: int = DEFAULT_DAYS) -> dict[str, Path]:
    """Create a CA and a server certificate for ``hosts`` in ``out_dir``.

    Args:
        hosts: IP addresses and/or DNS names the hub is reached by. Every
            address a workstation types into "Central Server Address" must be
            here, or certificate verification fails for that address.
        out_dir: Directory to write the four PEM files into; created if needed.
        days: Validity of the server certificate. The CA gets ten years.

    Returns:
        The paths written, keyed ``ca``, ``ca_key``, ``cert``, ``key``.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    if not hosts:
        raise ValueError("at least one --host is required")

    now = dt.datetime.now(dt.timezone.utc)
    out_dir.mkdir(parents=True, exist_ok=True)

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "VRTelemetry hub"),
            x509.NameAttribute(NameOID.COMMON_NAME, f"VRTelemetry hub CA ({hosts[0]})"),
        ]
    )
    ca_ski = x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key())
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(ca_ski, critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hosts[0])]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(_san_entries(hosts)), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=True,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ca_ski),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    def _key_pem(private_key: ec.EllipticCurvePrivateKey) -> bytes:
        return private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )

    paths = {
        "ca": out_dir / "hub-ca.pem",
        "ca_key": out_dir / "hub-ca-key.pem",
        "cert": out_dir / "hub-cert.pem",
        "key": out_dir / "hub-key.pem",
    }
    _write(paths["ca"], ca_cert.public_bytes(serialization.Encoding.PEM), private=False)
    _write(paths["ca_key"], _key_pem(ca_key), private=True)
    _write(paths["cert"], cert.public_bytes(serialization.Encoding.PEM), private=False)
    _write(paths["key"], _key_pem(key), private=True)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--host",
        action="append",
        required=True,
        help="IP address or DNS name workstations use to reach the hub (repeatable).",
    )
    parser.add_argument("--out-dir", type=Path, default=None, help="Where to write the PEM files.")
    parser.add_argument(
        "--days", type=int, default=DEFAULT_DAYS, help="Server certificate validity."
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing files.")
    args = parser.parse_args(argv)

    if importlib.util.find_spec("cryptography") is None:
        print(
            "This tool needs the 'cryptography' package: pip install cryptography",
            file=sys.stderr,
        )
        return 1

    out_dir = args.out_dir
    if out_dir is None:
        from src.config import get_settings

        out_dir = get_settings().paths.central_dir / "tls"
    out_dir = out_dir.expanduser().resolve()

    if (out_dir / "hub-key.pem").exists() and not args.force:
        print(
            f"{out_dir / 'hub-key.pem'} already exists; pass --force to replace it.",
            file=sys.stderr,
        )
        return 1

    paths = generate(args.host, out_dir, args.days)
    port = 9000
    print(f"Wrote the hub certificate for {', '.join(args.host)} to {out_dir}\n")
    print("On the HUB, in config.toml:")
    print("  [hub]")
    print(f"  tls_certfile = '{paths['cert']}'")
    print(f"  tls_keyfile = '{paths['key']}'\n")
    print(f"On EVERY WORKSTATION, copy {paths['ca'].name} somewhere local, then in config.toml:")
    print("  [central]")
    print("  ca_bundle = '<path to your copy of hub-ca.pem>'")
    print(f"and set the Central Server Address to https://{args.host[0]}:{port}\n")
    print(f"Keep {paths['ca_key'].name} offline; it is only needed to issue a new certificate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
