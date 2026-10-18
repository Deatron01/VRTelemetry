"""Pairing a workstation with a hub on another machine, by a short code.

The problem this solves is a chicken-and-egg one. A hub on a laboratory LAN
signs its TLS certificate with its own small CA (GDPR-01), so a workstation can
only verify the hub once it holds ``hub-ca.pem`` -- and the only way to get
that file used to be carrying it across on a USB stick. Fetching it over the
network means fetching it over a connection that cannot be verified yet, from
something that merely *claims* to be the hub.

So the workstation has to be convinced that the certificate came from the hub
an administrator is looking at. What the two share is a six-digit code the
administrator reads off the hub's admin UI.

**Why not "an HMAC of the fingerprint, keyed by the code".** It is the obvious
design, and a six-digit code makes it breakable offline. An attacker between
the two machines forwards the workstation's request to the real hub, reads the
reply -- the CA and ``HMAC(code, fingerprint)``, both of which it can see --
and tries all 10**6 codes against it in well under a second. Then it answers
the workstation with its own CA and a correct HMAC. Rate limiting on the hub
does not help: the guessing happens on the attacker's machine. The same holds
for any scheme where one side sends something computed only from the code and
public values.

**What this module does instead** is a password-authenticated key exchange,
SPEKE (Jablon 1996; IEEE 1363.2), over the 2048-bit MODP group of RFC 3526. It
needs nothing beyond the standard library, which matters because the
workstation does not ship ``cryptography``:

1. Both sides derive a generator from the code: ``g = H(code)**2 mod p``.
2. The workstation sends ``A = g**a``; the hub answers ``B = g**b``, its CA
   certificate, and a confirmation ``MAC(K, "hub" | fingerprint | A | B)``,
   where ``K`` is derived from ``g**(ab)`` and the transcript.
3. The workstation recomputes ``K`` and checks the confirmation. Only a party
   that knew the code can produce it, and it names this CA's fingerprint, so a
   substituted certificate fails.
4. The workstation answers with its own confirmation (``"workstation"``), so
   the hub knows the code was used by someone who knew it and retires it.

An attacker who does not know the code gets *one* guess per exchange, whichever
side it impersonates, and cannot test other guesses offline: checking a guess
means computing ``g'**(ab)`` from ``A`` or ``B``, which is a Diffie-Hellman
problem. The hub limits exchanges per code and per address
(:mod:`src.central_server.pairing`), so the odds stay near five in a million.

The two published weaknesses of plain SPEKE are closed the published way
(Hao & Shahandashti, 2014): the session key covers the whole transcript, which
stops an attacker raising both values to a common power, and the confirmations
are labelled by role, so one cannot be reflected back as the other.

This module holds the protocol itself, used by both ends, plus the workstation's
half of the exchange (:func:`pair_with_hub`). The hub's half -- codes, expiry,
attempt and rate limits -- is :mod:`src.central_server.pairing`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
import ssl
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config.workstation_kit import (
    CA_FILE_NAME,
    KitInstallResult,
    KitMergeError,
    install_workstation_kit,
    merge_central_block,
)

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
CONTEXT = b"VRTelemetry hub pairing v1"

#: Digits in a pairing code.
CODE_DIGITS = 6

#: RFC 3526, group 14: the 2048-bit MODP group. A safe prime, ``p = 2q + 1``.
P = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74"
    "020BBEA63B139B22514A08798E3404DDEF9519B3CD3A431B302B0A6DF25F1437"
    "4FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3DC2007CB8A163BF05"
    "98DA48361C55D39A69163FA8FD24CF5F83655D23DCA3AD961C62F356208552BB"
    "9ED529077096966D670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2BCBF695581718"
    "3995497CEA956AE515D2261898FA051015728E5A8AACAA68FFFFFFFFFFFFFFFF",
    16,
)
#: The order of the subgroup of squares, where every value in the exchange lives.
Q = (P - 1) // 2
_ELEMENT_BYTES = (P.bit_length() + 7) // 8


class PairingError(Exception):
    """A pairing exchange that did not succeed.

    ``status`` is the HTTP status the workstation's own API answers with, and
    ``reason`` a stable token the UI can recognise; the message is for people.
    """

    def __init__(self, status: int, reason: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.reason = reason
        self.message = message


def normalise_code(code: str) -> str:
    """``code`` without the spaces or dashes people type into it.

    Raises:
        ValueError: if what is left is not :data:`CODE_DIGITS` digits.
    """
    digits = re.sub(r"[\s-]", "", code or "")
    if not re.fullmatch(rf"\d{{{CODE_DIGITS}}}", digits):
        raise ValueError(f"a pairing code is {CODE_DIGITS} digits")
    return digits


def generator(code: str) -> int:
    """The SPEKE generator for ``code``: a hash of it, squared into the subgroup."""
    digest = hashlib.shake_256(CONTEXT + b"|generator|" + normalise_code(code).encode()).digest(
        _ELEMENT_BYTES + 32
    )
    g = pow(int.from_bytes(digest, "big") % P, 2, P)
    if g <= 1:  # pragma: no cover - probability about 2**-2048
        raise ValueError("degenerate generator")
    return g


def validate_element(value: int) -> int:
    """``value`` if it is a non-trivial member of the subgroup, else raise.

    A peer that sends 1, ``p - 1`` or something outside the subgroup would
    force the shared secret into a tiny set an attacker can enumerate.
    """
    if not 1 < value < P - 1 or pow(value, Q, P) != 1:
        raise ValueError("not a valid group element")
    return value


def new_ephemeral(g: int) -> tuple[int, int]:
    """A fresh secret exponent and its public value ``g**x``."""
    x = secrets.randbelow(Q - 2) + 2
    return x, pow(g, x, P)


def encode_element(value: int) -> str:
    return value.to_bytes(_ELEMENT_BYTES, "big").hex()


def decode_element(text: Any) -> int:
    """A group element from its wire form, validated."""
    if not isinstance(text, str) or not re.fullmatch(r"[0-9a-fA-F]{1,1024}", text):
        raise ValueError("not a hex-encoded group element")
    return validate_element(int(text, 16))


def session_key(own_secret: int, peer_public: int, a_value: int, b_value: int) -> bytes:
    """The key both sides derive: the shared secret, bound to the transcript."""
    shared = validate_element(pow(peer_public, own_secret, P))
    material = b"".join(v.to_bytes(_ELEMENT_BYTES, "big") for v in (a_value, b_value, shared))
    return hashlib.sha256(CONTEXT + b"|key|" + material).digest()


def _confirmation(role: bytes, key: bytes, fingerprint: bytes, a_value: int, b_value: int) -> str:
    message = b"|".join(
        (
            CONTEXT,
            b"confirm",
            role,
            fingerprint,
            a_value.to_bytes(_ELEMENT_BYTES, "big"),
            b_value.to_bytes(_ELEMENT_BYTES, "big"),
        )
    )
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def hub_confirmation(key: bytes, fingerprint: bytes, a_value: int, b_value: int) -> str:
    """The hub's proof that it knows the code *and* is sending this certificate."""
    return _confirmation(b"hub", key, fingerprint, a_value, b_value)


def workstation_confirmation(key: bytes, fingerprint: bytes, a_value: int, b_value: int) -> str:
    """The workstation's proof that it knew the code, so the hub can retire it."""
    return _confirmation(b"workstation", key, fingerprint, a_value, b_value)


def confirmations_match(expected: str, received: Any) -> bool:
    return isinstance(received, str) and hmac.compare_digest(expected, received)


def certificate_der(pem: str) -> bytes:
    """The DER bytes of the one certificate in ``pem``.

    Exactly one: the hub sends its CA and nothing else, and a bundle with an
    extra certificate in it would make the workstation trust that one too.
    """
    if not isinstance(pem, str) or pem.count("-----BEGIN CERTIFICATE-----") != 1:
        raise ValueError("expected exactly one PEM certificate")
    body = pem.strip()
    if not body.startswith("-----BEGIN CERTIFICATE-----") or not body.endswith(
        "-----END CERTIFICATE-----"
    ):
        raise ValueError("expected exactly one PEM certificate")
    inner = body[len("-----BEGIN CERTIFICATE-----") : -len("-----END CERTIFICATE-----")]
    try:
        return base64.b64decode("".join(inner.split()), validate=True)
    except ValueError as exc:
        raise ValueError("the certificate is not valid base64") from exc


def fingerprint(der: bytes) -> bytes:
    """SHA-256 over the DER certificate -- what ``openssl x509 -fingerprint -sha256`` shows."""
    return hashlib.sha256(der).digest()


def format_fingerprint(digest: bytes) -> str:
    """``AB:CD:...``, the way certificate viewers print one."""
    return ":".join(f"{byte:02X}" for byte in digest)


# ─────────────────────────────────────────────────────────────────────────────
# The workstation's half
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PairingResult:
    url: str
    fingerprint: str
    kit: KitInstallResult
    #: Whether the running backend already trusts the new CA, or needs a restart.
    applied_now: bool


def _hub_error(response: Any, url: str) -> PairingError:
    """What the hub refused, in the workstation's words."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, dict):
        reason = str(detail.get("reason") or "")
        message = str(detail.get("message") or reason)
    else:
        reason, message = str(detail or ""), str(detail or "")

    status = response.status_code
    if status == 429:
        return PairingError(429, reason or "rate_limited", message or "Too many pairing attempts.")
    if status in (404, 410):
        return PairingError(409, reason or "no_pairing_code", message or "No active pairing code.")
    return PairingError(
        502,
        reason or "hub_error",
        f"{url} answered HTTP {status}{': ' + message if message else ''}. "
        "Is this a VRTelemetry hub that supports pairing?",
    )


def _unverified(call: Any, *args: Any, **kwargs: Any) -> Any:
    """Make one request without certificate verification, quietly.

    The one request in the application that is allowed to: the workstation
    does not hold the hub's CA yet, which is the point of pairing. What
    replaces the certificate check is the hub's confirmation, checked by the
    caller before anything in the reply is believed.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Unverified HTTPS request")
        return call(*args, verify=False, **kwargs)


def pair_with_hub(
    http: Any,
    url: str,
    code: str,
    data_root: Path,
    *,
    ca_bundle_value: str | None = None,
    timeout: float = 10.0,
) -> PairingResult:
    """Fetch the hub's CA, authenticated by ``code``, and install it.

    Steps, in the order they can fail:

    1. the key exchange over an unverified connection (``/pairing/start``),
       and the hub's confirmation, which proves the certificate is its own;
    2. a request *verified* against that certificate (``/health``), which
       catches a certificate that does not cover the address typed -- better
       now than on the first upload;
    3. the workstation's confirmation (``/pairing/finish``), over the verified
       connection, which retires the code;
    4. ``hub-ca.pem`` and ``[central]`` written into ``data_root``.

    Nothing is written until all three requests succeed.

    Args:
        http: The container's HTTP client.
        url: The hub address, ``https://<host>:<port>``.
        code: The pairing code from the hub's admin UI.
        data_root: Where ``hub-ca.pem`` and ``config.toml`` go.
        ca_bundle_value: ``central.ca_bundle`` as written; defaults to the
            relative ``hub-ca.pem``.
        timeout: Seconds, per request.

    Raises:
        PairingError: naming the step that failed.
    """
    url = (url or "").strip().rstrip("/")
    if not url.startswith("https://"):
        raise PairingError(
            400,
            "https_required",
            "Pairing needs the hub's https:// address, e.g. https://192.168.1.50:9000.",
        )
    try:
        g = generator(code)
    except ValueError as exc:
        raise PairingError(
            400, "invalid_code", f"The pairing code is {CODE_DIGITS} digits."
        ) from exc

    # Before any request: a config.toml that cannot be merged into would
    # otherwise be discovered after the hub had already retired the code.
    config_path = data_root / "config.toml"
    if config_path.is_file():
        try:
            merge_central_block(
                config_path.read_text(encoding="utf-8"), url, ca_bundle_value or CA_FILE_NAME
            )
        except KitMergeError as exc:
            raise PairingError(
                409,
                "config_not_mergeable",
                f"{config_path} could not be updated: {exc}. Fix it, or set [central] "
                f'url = "{url}" and ca_bundle = "{CA_FILE_NAME}" in it by hand.',
            ) from exc

    a_secret, a_value = new_ephemeral(g)
    try:
        response = _unverified(
            http.post,
            f"{url}/pairing/start",
            json={"version": PROTOCOL_VERSION, "A": encode_element(a_value)},
            timeout=timeout,
        )
    except http.RequestException as exc:
        raise PairingError(502, "hub_unreachable", f"Could not reach {url}: {exc}") from exc
    if response.status_code != 200:
        raise _hub_error(response, url)

    try:
        body = response.json()
        b_value = decode_element(body.get("B"))
        ca_pem = body.get("ca_pem")
        der = certificate_der(ca_pem)
        attempt_id = body.get("attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id:
            raise ValueError("no attempt_id")
        key = session_key(a_secret, b_value, a_value, b_value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise PairingError(
            502, "bad_hub_reply", f"{url} sent a pairing reply this app cannot read: {exc}"
        ) from exc

    digest = fingerprint(der)
    if not confirmations_match(
        hub_confirmation(key, digest, a_value, b_value), body.get("confirm")
    ):
        # Either the code is wrong, or whatever answered is not the hub that
        # issued it. Indistinguishable from here, and both mean "do not trust".
        logger.warning(f"Pairing with {url} rejected: the hub's confirmation did not verify")
        raise PairingError(
            400,
            "code_rejected",
            "The hub did not confirm this code. Check the code (it expires after ten "
            "minutes and works once), or generate a new one in the hub's admin UI. If the "
            "code is right, something other than the hub answered at this address.",
        )

    canonical_pem = ssl.DER_cert_to_PEM_cert(der)
    data_root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=data_root, prefix=".pairing-", suffix=".pem", delete=False, encoding="ascii"
    ) as handle:
        handle.write(canonical_pem)
    candidate = Path(handle.name)
    try:
        try:
            health = http.get(f"{url}/health", verify=str(candidate), timeout=timeout)
        except http.RequestException as exc:
            raise PairingError(
                502,
                "certificate_mismatch",
                f"The hub proved its identity, but its TLS certificate does not verify for "
                f"{url}: {exc}. The certificate must name the address typed here; regenerate "
                "it on the hub with that address (vrtelemetry-hub gen-cert --host <address>).",
            ) from exc
        if health.status_code != 200:
            raise _hub_error(health, url)

        try:
            finish = http.post(
                f"{url}/pairing/finish",
                json={
                    "attempt_id": attempt_id,
                    "confirm": workstation_confirmation(key, digest, a_value, b_value),
                },
                verify=str(candidate),
                timeout=timeout,
            )
        except http.RequestException as exc:
            raise PairingError(502, "hub_unreachable", f"Could not reach {url}: {exc}") from exc
        if finish.status_code != 200:
            raise _hub_error(finish, url)
    finally:
        candidate.unlink(missing_ok=True)

    try:
        kit = install_workstation_kit(data_root, url, canonical_pem, ca_bundle=ca_bundle_value)
    except KitMergeError as exc:
        raise PairingError(
            409,
            "config_not_mergeable",
            f"Paired, but {data_root / 'config.toml'} could not be updated: {exc}. "
            f'Set [central] url = "{url}" and ca_bundle = "{CA_FILE_NAME}" in it by hand.',
        ) from exc

    trust = getattr(http, "trust_ca_bundle", None)
    applied_now = False
    if callable(trust):
        trust(kit.ca_path)
        applied_now = True
    logger.info(f"Paired with the hub at {url}; CA fingerprint {format_fingerprint(digest)}")
    return PairingResult(
        url=url, fingerprint=format_fingerprint(digest), kit=kit, applied_now=applied_now
    )
