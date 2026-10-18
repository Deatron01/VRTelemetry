# tests/unit/test_transport.py
"""The HTTP port and its one production implementation (VRT-14).

Small file, and the reason it exists is narrow: ``default_http_client()``
returns the ``requests`` module through a ``cast``, and a cast is a promise the
type checker takes on faith. These tests are where the promise is checked.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.application.ports import HttpClient
from src.infrastructure.transport import default_http_client


def test_the_real_client_satisfies_the_port():
    """The cast in `default_http_client` is not a lie.

    If `requests` ever loses one of the four verbs, or moves
    `RequestException`, this fails here rather than at the first upload on a
    researcher's machine.
    """
    client = default_http_client()

    assert isinstance(client, HttpClient)
    for verb in ("get", "post", "put", "delete"):
        assert callable(getattr(client, verb))
    assert issubclass(client.RequestException, Exception)


def test_importing_the_transport_module_does_not_import_requests():
    """`requests` is imported inside the function, and that is load-bearing.

    ``tests/unit/test_no_import_time_io.py`` asserts that importing any module
    under ``src/`` performs no I/O. ``requests`` initialises its adapters and
    TLS stack on import, so hoisting that import to module scope would put it
    back into every import of the application.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import src.infrastructure.transport; print('requests' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False", (
        "importing src.infrastructure.transport pulled in requests; "
        "the import belongs inside default_http_client()"
    )


def test_a_stub_missing_the_exception_type_is_not_a_client():
    """The attribute every caller catches on is part of the contract.

    A fake with the four verbs and no ``RequestException`` produces a suite
    where the offline branch is never reached -- the exact shape of the
    false-green fixture VRT-12 removed.
    """

    class _VerbsOnly:
        def get(self, url: str, **kwargs: Any) -> Any: ...
        def post(self, url: str, **kwargs: Any) -> Any: ...
        def put(self, url: str, **kwargs: Any) -> Any: ...
        def delete(self, url: str, **kwargs: Any) -> Any: ...

    assert not isinstance(_VerbsOnly(), HttpClient)


@pytest.mark.parametrize("missing", ["get", "post", "put", "delete"])
def test_a_stub_missing_a_verb_is_not_a_client(missing: str):
    """All four verbs are used by some router, so all four are required."""
    import requests

    namespace: dict[str, Any] = {"RequestException": requests.RequestException}
    for verb in ("get", "post", "put", "delete"):
        if verb != missing:
            namespace[verb] = lambda *_args, **_kwargs: None

    stub_type = type("_PartialClient", (), namespace)
    assert not isinstance(stub_type(), HttpClient)


# --------------------------------------------------------------------------- #
# The TLS policy (GDPR-01)
# --------------------------------------------------------------------------- #


class _Recorder:
    """An inner client that records what it was asked to send, and sends nothing."""

    def __init__(self) -> None:
        import requests

        self.RequestException = requests.RequestException
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _call(self, method: str, url: str, kwargs: dict[str, Any]) -> str:
        self.calls.append((method, url, kwargs))
        return "sent"

    def get(self, url: str, **kwargs: Any) -> Any:
        return self._call("GET", url, kwargs)

    def post(self, url: str, **kwargs: Any) -> Any:
        return self._call("POST", url, kwargs)

    def put(self, url: str, **kwargs: Any) -> Any:
        return self._call("PUT", url, kwargs)

    def delete(self, url: str, **kwargs: Any) -> Any:
        return self._call("DELETE", url, kwargs)


def _client(**policy: Any):
    from src.infrastructure.transport import PolicyEnforcingHttpClient, TlsPolicy

    inner = _Recorder()
    return PolicyEnforcingHttpClient(inner, TlsPolicy(**policy)), inner


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.50:9000/data/upload-patient",
        "http://hub.lab.local:9000/health",
        "ftp://192.168.1.50/x",
    ],
)
def test_plain_http_to_the_network_is_refused_before_anything_is_sent(url: str) -> None:
    """The refusal is a RequestException, so every caller queues instead of crashing."""
    client, inner = _client()

    with pytest.raises(client.RequestException, match="insecure_transport_refused"):
        client.post(url, json={"patient": {"patient_id": "p"}})

    assert inner.calls == [], "the request reached the wire"


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:9000/health", "http://localhost:9000/health", "http://[::1]:9000/health"],
)
def test_plain_http_to_loopback_is_allowed(url: str) -> None:
    """A one-machine setup: the traffic never leaves the host."""
    client, inner = _client()

    assert client.get(url) == "sent"
    assert inner.calls[0][1] == url


def test_https_is_allowed_and_trusts_the_configured_ca(tmp_path) -> None:
    ca = tmp_path / "hub-ca.pem"
    ca.write_text("-----BEGIN CERTIFICATE-----\n")
    client, inner = _client(ca_bundle=ca)

    client.post("https://192.168.1.50:9000/data/upload-session", data={})

    assert inner.calls[0][2]["verify"] == str(ca)


def test_an_explicit_verify_argument_is_not_overridden(tmp_path) -> None:
    client, inner = _client(ca_bundle=tmp_path / "hub-ca.pem")

    client.get("https://hub:9000/health", verify=False)

    assert inner.calls[0][2]["verify"] is False


def test_without_a_ca_bundle_the_system_trust_store_is_used() -> None:
    client, inner = _client()

    client.get("https://hub.example.org/health")

    assert "verify" not in inner.calls[0][2]


def test_the_development_flag_lets_plain_http_through() -> None:
    client, _ = _client(allow_insecure_http=True)

    assert client.post("http://192.168.1.50:9000/data/upload-patient") == "sent"


def test_the_production_client_carries_the_policy() -> None:
    """`default_http_client` returns the wrapper, not bare `requests`."""
    from src.config.settings import CentralServerSettings
    from src.infrastructure.transport import PolicyEnforcingHttpClient

    client = default_http_client(CentralServerSettings())

    assert isinstance(client, PolicyEnforcingHttpClient)
    with pytest.raises(client.RequestException, match="insecure_transport_refused"):
        client.get("http://10.0.0.9:9000/health", timeout=0.01)


def test_a_missing_ca_bundle_fails_at_startup_naming_the_file(tmp_path) -> None:
    from pydantic import ValidationError

    from src.config.settings import CentralServerSettings

    with pytest.raises(ValidationError, match="does not exist"):
        CentralServerSettings(ca_bundle=tmp_path / "nope.pem")


def test_a_hub_certificate_without_its_key_is_rejected(tmp_path) -> None:
    from pydantic import ValidationError

    from src.config.settings import HubSettings

    with pytest.raises(ValidationError, match="set together"):
        HubSettings(tls_certfile=tmp_path / "hub-cert.pem")


@pytest.mark.parametrize("url", ["/auth/register", "/license/activate"])
def test_a_missing_hub_address_says_so_instead_of_blaming_tls(url: str) -> None:
    """No hub configured: callers build "/auth/register" from an empty base URL.

    Still refused before anything is sent, but the message used to read
    "refusing to send data to :// without TLS" -- which sent a researcher after
    certificates when the workstation simply had no hub address.
    """
    client, inner = _client()

    with pytest.raises(client.RequestException) as refused:
        client.post(url, data={})

    message = str(refused.value)
    assert "no_hub_address" in message
    assert "without TLS" not in message
    assert "workstation kit" in message
    assert inner.calls == [], "the request reached the wire"
