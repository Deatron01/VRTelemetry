"""Pairing a workstation with a hub by code: the protocol and the hub's limits.

The end-to-end path -- the workstation's route talking to the hub's routes --
is tests/integration/test_hub_pairing_flow.py. This file covers the two pieces it is
made of, :mod:`src.infrastructure.hub_pairing` (the key exchange, shared) and
:class:`src.central_server.pairing.PairingService` (codes, expiry, attempt and
rate limits), with a fake clock so expiry is not a ten-minute sleep.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")

from src.central_server.pairing import PairingRefusedError, PairingService
from src.infrastructure import hub_pairing as protocol
from src.infrastructure.transport import PolicyEnforcingHttpClient, TlsPolicy


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(scope="module")
def ca_pem(tmp_path_factory: pytest.TempPathFactory) -> str:
    pytest.importorskip("cryptography")
    from src.central_server import certificates

    paths = certificates.generate(["192.168.1.50"], tmp_path_factory.mktemp("tls"))
    return paths["ca"].read_text(encoding="ascii")


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def service(ca_pem: str, clock: FakeClock) -> PairingService:
    return PairingService(lambda: ca_pem, clock=clock)


def workstation_start(code: str) -> tuple[int, int, dict[str, Any]]:
    """The workstation's first message for ``code``: its secret, A, and the body."""
    a_secret, a_value = protocol.new_ephemeral(protocol.generator(code))
    return a_secret, a_value, {"A": protocol.encode_element(a_value)}


def workstation_check(
    code_reply: dict[str, Any], a_secret: int, a_value: int
) -> tuple[bool, bytes, bytes, int]:
    """Whether the hub's confirmation verifies, as the workstation computes it."""
    b_value = protocol.decode_element(code_reply["B"])
    key = protocol.session_key(a_secret, b_value, a_value, b_value)
    digest = protocol.fingerprint(protocol.certificate_der(code_reply["ca_pem"]))
    expected = protocol.hub_confirmation(key, digest, a_value, b_value)
    return protocol.confirmations_match(expected, code_reply["confirm"]), key, digest, b_value


def exchange(service: PairingService, code: str, client: str = "10.0.0.2") -> dict[str, Any]:
    """A whole pairing as an honest workstation that was given ``code`` runs it."""
    a_secret, a_value, body = workstation_start(code)
    reply = service.start(body["A"], client)
    ok, key, digest, b_value = workstation_check(reply, a_secret, a_value)
    if not ok:
        return {"verified": False}
    confirm = protocol.workstation_confirmation(key, digest, a_value, b_value)
    return {"verified": True, **service.finish(reply["attempt_id"], confirm, client)}


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 10**6:06d}"


# ─────────────────────────────────────────────────────────────────────────────
# The protocol
# ─────────────────────────────────────────────────────────────────────────────


def test_both_sides_derive_the_same_key_from_the_same_code() -> None:
    g = protocol.generator("123456")
    a, big_a = protocol.new_ephemeral(g)
    b, big_b = protocol.new_ephemeral(g)

    assert protocol.session_key(a, big_b, big_a, big_b) == protocol.session_key(
        b, big_a, big_a, big_b
    )


def test_different_codes_give_different_keys() -> None:
    a, big_a = protocol.new_ephemeral(protocol.generator("123456"))
    b, big_b = protocol.new_ephemeral(protocol.generator("654321"))

    assert protocol.session_key(a, big_b, big_a, big_b) != protocol.session_key(
        b, big_a, big_a, big_b
    )


def test_the_confirmation_names_the_certificate() -> None:
    """A substituted certificate fails, even with the right code and key."""
    key = b"k" * 32
    honest = protocol.hub_confirmation(key, b"\x01" * 32, 2, 3)

    assert honest != protocol.hub_confirmation(key, b"\x02" * 32, 2, 3)
    assert honest != protocol.workstation_confirmation(key, b"\x01" * 32, 2, 3), (
        "the roles are labelled, so one confirmation cannot be reflected as the other"
    )


@pytest.mark.parametrize("value", [0, 1, protocol.P - 1, protocol.P, protocol.P + 5])
def test_degenerate_group_elements_are_rejected(value: int) -> None:
    with pytest.raises(ValueError):
        protocol.validate_element(value)


def test_an_element_outside_the_subgroup_is_rejected() -> None:
    non_residue = next(x for x in range(2, 1000) if pow(x, protocol.Q, protocol.P) != 1)

    with pytest.raises(ValueError):
        protocol.validate_element(non_residue)


@pytest.mark.parametrize("typed", ["123 456", "123-456", " 123456 "])
def test_codes_are_accepted_as_people_type_them(typed: str) -> None:
    assert protocol.normalise_code(typed) == "123456"
    assert protocol.generator(typed) == protocol.generator("123456")


@pytest.mark.parametrize("typed", ["", "12345", "1234567", "12345a"])
def test_malformed_codes_are_refused(typed: str) -> None:
    with pytest.raises(ValueError):
        protocol.normalise_code(typed)


def test_a_bundle_with_two_certificates_is_refused(ca_pem: str) -> None:
    with pytest.raises(ValueError):
        protocol.certificate_der(ca_pem + ca_pem)


# ─────────────────────────────────────────────────────────────────────────────
# The hub's codes and limits
# ─────────────────────────────────────────────────────────────────────────────


def test_a_valid_code_pairs_and_is_then_retired(service: PairingService) -> None:
    issued = service.issue("admin@lab")

    assert len(issued["code"]) == 6 and issued["code"].isdigit()
    assert issued["state"] == "active"
    assert exchange(service, issued["code"]) == {"verified": True, "ok": True}
    status = service.status()
    assert status["state"] == "used"
    assert status["used_by"] == "10.0.0.2"
    assert status["code"] is None, "a used code is not shown again"


def test_a_wrong_code_does_not_verify_and_cannot_finish(service: PairingService) -> None:
    code = service.issue("admin@lab")["code"]
    a_secret, a_value, body = workstation_start(wrong(code))

    reply = service.start(body["A"], "10.0.0.2")
    ok, key, digest, b_value = workstation_check(reply, a_secret, a_value)

    assert not ok, "the workstation must not trust the certificate"
    with pytest.raises(PairingRefusedError) as refused:
        service.finish(
            reply["attempt_id"],
            protocol.workstation_confirmation(key, digest, a_value, b_value),
            "10.0.0.2",
        )
    assert refused.value.status == 403
    assert service.status()["state"] == "active", "the code survives a typo"
    assert service.status()["attempts"] == 1


def test_an_expired_code_is_refused(service: PairingService, clock: FakeClock) -> None:
    code = service.issue("admin@lab")["code"]
    clock.now += 601

    with pytest.raises(PairingRefusedError) as refused:
        exchange(service, code)

    assert (refused.value.status, refused.value.reason) == (410, "pairing_code_expired")
    assert service.status()["state"] == "expired"


def test_a_code_that_expires_mid_exchange_cannot_finish(
    service: PairingService, clock: FakeClock
) -> None:
    code = service.issue("admin@lab")["code"]
    a_secret, a_value, body = workstation_start(code)
    reply = service.start(body["A"], "10.0.0.2")
    _, key, digest, b_value = workstation_check(reply, a_secret, a_value)
    clock.now += 601

    with pytest.raises(PairingRefusedError):
        service.finish(
            reply["attempt_id"],
            protocol.workstation_confirmation(key, digest, a_value, b_value),
            "10.0.0.2",
        )


def test_a_used_code_cannot_be_reused(service: PairingService) -> None:
    code = service.issue("admin@lab")["code"]
    exchange(service, code, client="10.0.0.2")

    with pytest.raises(PairingRefusedError) as refused:
        exchange(service, code, client="10.0.0.3")

    assert (refused.value.status, refused.value.reason) == (410, "pairing_code_used")


def test_a_code_locks_after_five_attempts(ca_pem: str, clock: FakeClock) -> None:
    """Every start counts -- the hub cannot tell a wrong code from a right one."""
    service = PairingService(lambda: ca_pem, clock=clock, rate_per_address=100)
    code = service.issue("admin@lab")["code"]
    for _ in range(5):
        assert exchange(service, wrong(code)) == {"verified": False}

    with pytest.raises(PairingRefusedError) as refused:
        exchange(service, code)

    assert (refused.value.status, refused.value.reason) == (410, "pairing_code_locked")
    assert service.status()["state"] == "locked"


def test_requests_are_rate_limited_per_address(service: PairingService, clock: FakeClock) -> None:
    service.issue("admin@lab")
    for _ in range(10):
        with pytest.raises(PairingRefusedError) as refused:
            service.finish("no-such-attempt", "x", "10.0.0.9")
        assert refused.value.status == 403

    with pytest.raises(PairingRefusedError) as limited:
        service.finish("no-such-attempt", "x", "10.0.0.9")
    assert limited.value.status == 429
    assert limited.value.retry_after and limited.value.retry_after > 0

    # Another machine is not held up by this one...
    code = service.issue("admin@lab")["code"]
    assert exchange(service, code, client="10.0.0.2")["verified"]
    # ...and the limited one recovers once the window has passed.
    clock.now += 61
    with pytest.raises(PairingRefusedError) as later:
        service.finish("no-such-attempt", "x", "10.0.0.9")
    assert later.value.status == 403


def test_the_whole_hub_is_rate_limited_too(ca_pem: str, clock: FakeClock) -> None:
    service = PairingService(lambda: ca_pem, clock=clock, rate_per_address=100, rate_overall=3)
    for address in ("10.0.0.1", "10.0.0.2", "10.0.0.3"):
        with pytest.raises(PairingRefusedError):
            service.finish("x", "x", address)

    with pytest.raises(PairingRefusedError) as limited:
        service.finish("x", "x", "10.0.0.4")
    assert limited.value.status == 429


def test_issuing_a_new_code_replaces_the_old_one(service: PairingService) -> None:
    old = service.issue("admin@lab")["code"]
    a_secret, a_value, body = workstation_start(old)
    reply = service.start(body["A"], "10.0.0.2")
    _, key, digest, b_value = workstation_check(reply, a_secret, a_value)

    service.issue("admin@lab")

    with pytest.raises(PairingRefusedError):
        service.finish(
            reply["attempt_id"],
            protocol.workstation_confirmation(key, digest, a_value, b_value),
            "10.0.0.2",
        )


def test_a_malformed_first_message_is_not_counted(service: PairingService) -> None:
    service.issue("admin@lab")

    with pytest.raises(PairingRefusedError) as refused:
        service.start("01", "10.0.0.2")

    assert refused.value.status == 400
    assert service.status()["attempts"] == 0


def test_with_no_code_issued_there_is_nothing_to_pair_with(service: PairingService) -> None:
    with pytest.raises(PairingRefusedError) as refused:
        exchange(service, "123456")
    assert refused.value.status == 404


def test_a_hub_without_a_ca_cannot_issue_codes(tmp_path: Path) -> None:
    service = PairingService(lambda: (tmp_path / "missing.pem").read_text())

    with pytest.raises(PairingRefusedError) as refused:
        service.issue("admin@lab")
    assert refused.value.status == 503


# ─────────────────────────────────────────────────────────────────────────────
# The transport after pairing
# ─────────────────────────────────────────────────────────────────────────────


def test_the_transport_uses_a_newly_paired_ca_at_once(tmp_path: Path) -> None:
    class Recorder:
        RequestException = OSError

        def __init__(self) -> None:
            self.kwargs: dict[str, Any] = {}

        def get(self, _url: str, **kwargs: Any) -> None:
            self.kwargs = kwargs

    inner = Recorder()
    client = PolicyEnforcingHttpClient(inner, TlsPolicy())  # type: ignore[arg-type]
    client.trust_ca_bundle(tmp_path / "hub-ca.pem")

    client.get("https://hub:9000/health")

    assert inner.kwargs["verify"] == str(tmp_path / "hub-ca.pem")
