# tests/integration/test_hub_connection.py
"""Connecting a workstation to a hub on another machine (VRT-16a).

The two-machine setup is the normal one — a hub in the lab, workstations
around it — and until now the first thing that told a researcher their hub
address was wrong was a failed upload at the *end* of a recording. The address
involves an IP that changes, a port, and a firewall; there was nothing to ask
"does this work?" before committing a session to it.

So there are now two halves, and this file tests both: ``GET /health`` on the
hub, and ``POST /api/config/central-server/check`` on the workstation, which
asks the hub on the researcher's behalf and reports what came back.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from src.central_server.server import resolve_bind_address
from src.config import PathSettings, Settings
from src.interfaces.api.app import create_app
from src.interfaces.api.container import build_container

REPO_ROOT = Path(__file__).resolve().parents[2]


# ─────────────────────────────────────────────────────────────────────────────
# The hub end
# ─────────────────────────────────────────────────────────────────────────────


def _hub_health_in_subprocess(data_root: Path, env: dict[str, str]) -> dict[str, Any]:
    """Call the hub's health route in a clean interpreter, against ``data_root``.

    A subprocess because importing ``src.central_server.server`` initialises two
    SQLite schemas at module scope — see ``KNOWN_IMPORT_TIME_IO`` in
    tests/unit/test_no_import_time_io.py, which records that as VRT-15's to fix.
    Importing it in-process would create those databases wherever the suite
    happens to be pointed, and would do it once for every test session
    afterwards.
    """
    source = (
        "import json, sys;"
        f"sys.path.insert(0, {str(REPO_ROOT)!r});"
        "from src.central_server.server import health;"
        "print(json.dumps(health()))"
    )
    result = subprocess.run(  # noqa: S603 - the argv is this file's own literal
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_hub_reports_itself_and_its_database(tmp_path: Path, child_env) -> None:
    """What an operator gets from `curl http://<hub>:9000/health`.

    ``service`` is the field that matters most and is easy to overlook: a
    workstation pointed at the wrong service on the right port gets a reply, and
    without a name in it would look connected.
    """
    body = _hub_health_in_subprocess(
        tmp_path,
        child_env(drop_prefix="VRT_", VRT_PATHS__DATA_ROOT=str(tmp_path)),
    )

    assert body["service"] == "vrtelemetry-hub"
    assert body["database"] == "ok"
    assert body["ok"] is True
    assert body["version"]


def test_the_hub_binds_all_interfaces_by_default() -> None:
    """A LAN service, unlike the workstation API, which is loopback on purpose.

    A hub bound to 127.0.0.1 is reachable from precisely the machine that does
    not need it.
    """
    host, port = resolve_bind_address()

    # Asserting the intent, not choosing it; S104 is not selected for tests/.
    assert host == "0.0.0.0"
    assert port == 9000


def test_the_pre_vrt6_environment_variables_still_move_the_hub(monkeypatch) -> None:
    """Honoured, not ignored.

    ``main()`` read ``VRT_HUB_HOST`` / ``VRT_HUB_PORT`` -- single underscore --
    which is not what pydantic-settings binds, so the *documented* way to move
    the hub silently did nothing and the way that worked was documented nowhere.
    Both work now; a deployment still using the old spelling gets a warning
    rather than a surprise.
    """
    monkeypatch.setenv("VRT_HUB_HOST", "10.0.0.7")
    monkeypatch.setenv("VRT_HUB_PORT", "9100")

    assert resolve_bind_address() == ("10.0.0.7", 9100)


# ─────────────────────────────────────────────────────────────────────────────
# The workstation end
# ─────────────────────────────────────────────────────────────────────────────


class _Answering:
    """An HTTP client that returns one scripted response to every GET."""

    def __init__(self, status: int = 200, payload: Any = None, text: str = "") -> None:
        import requests

        self.RequestException = requests.RequestException
        self.status = status
        self.payload = payload
        self.text = text
        self.urls: list[str] = []

    def get(self, url: str, *_: Any, **__: Any) -> Any:
        self.urls.append(url)
        return self

    def post(self, url: str, *_: Any, **__: Any) -> Any:
        self.urls.append(url)
        return self

    # The response half of the same object, which is all the route reads.
    @property
    def status_code(self) -> int:
        return self.status

    def json(self) -> Any:
        if self.payload is None:
            raise ValueError("not JSON")
        return self.payload


class _Unreachable:
    def __init__(self) -> None:
        import requests

        self.RequestException = requests.RequestException

    def get(self, _url: str, *_a: Any, **_k: Any) -> Any:
        raise self.RequestException("No route to host")

    def post(self, _url: str, *_a: Any, **_k: Any) -> Any:
        raise self.RequestException("No route to host")


def _client(tmp_path: Path, http: Any, configured: str | None = None) -> TestClient:
    container = build_container(Settings(paths=PathSettings(data_root=tmp_path)), http=http)
    if configured:
        container.local_cache.set_config("central_server_url", configured)
    return TestClient(create_app(container))


def test_checking_an_unconfigured_workstation_says_so(tmp_path: Path) -> None:
    """Rather than reporting a failed request against an empty address.

    An unconfigured hub is a supported state, so the answer is "you have not set
    one", not "the network is broken".
    """
    response = _client(tmp_path, _Unreachable()).post("/api/config/central-server/check", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is False
    assert "No central server address is configured" in body["detail"]


def test_an_unreachable_hub_is_reported_with_its_address(tmp_path: Path) -> None:
    """The address is in the message because the address is usually the bug."""
    client = _client(tmp_path, _Unreachable(), configured="http://10.0.0.99:9000")

    body = client.post("/api/config/central-server/check", json={}).json()

    assert body["reachable"] is False
    assert body["url"] == "http://10.0.0.99:9000"
    assert "No route to host" in body["detail"]


def test_an_address_can_be_checked_before_it_is_saved(tmp_path: Path) -> None:
    """Checking and configuring are different acts.

    A researcher types an address and wants to know whether it works *before*
    committing to it -- and an address that fails the check is still a
    legitimate thing to save later, because the hub may simply be switched off.
    """
    http = _Answering(payload={"ok": True, "service": "vrtelemetry-hub", "version": "1.0.0"})
    client = _client(tmp_path, http, configured="http://saved:9000")

    body = client.post(
        "/api/config/central-server/check",
        json={"central_server_url": "http://typed:9000/"},
    ).json()

    assert body["url"] == "http://typed:9000"
    assert http.urls == ["http://typed:9000/health"], "the typed address is the one tested"
    assert client.get("/api/config/central-server").json()["central_server_url"] == (
        "http://saved:9000"
    ), "checking must not save"


def test_a_reachable_hub_reports_what_answered(tmp_path: Path) -> None:
    http = _Answering(
        payload={"ok": True, "service": "vrtelemetry-hub", "version": "1.2.3", "database": "ok"}
    )
    client = _client(tmp_path, http, configured="http://hub:9000")

    body = client.post("/api/config/central-server/check", json={}).json()

    assert body == {
        "reachable": True,
        "url": "http://hub:9000",
        "service": "vrtelemetry-hub",
        "version": "1.2.3",
        "database": "ok",
        "healthy": True,
    }


def test_something_else_listening_on_the_port_is_not_a_hub(tmp_path: Path) -> None:
    """A reply is not a connection.

    A router's admin page, another service, a captive portal -- all answer. The
    failure this prevents is a workstation that looks configured, records a
    study, and uploads nothing.
    """
    client = _client(tmp_path, _Answering(status=200, payload=None), configured="http://hub:9000")

    body = client.post("/api/config/central-server/check", json={}).json()

    assert body["reachable"] is False
    assert "not a VRTelemetry hub" in body["detail"]


def test_a_non_200_from_the_port_is_reported_with_its_status(tmp_path: Path) -> None:
    client = _client(tmp_path, _Answering(status=404), configured="http://hub:9000")

    body = client.post("/api/config/central-server/check", json={}).json()

    assert body["reachable"] is False
    assert "HTTP 404" in body["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# TLS (GDPR-01)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def hub_settings(monkeypatch, tmp_path: Path):
    """Point get_settings() at the environment this test sets, and back afterwards.

    The data root moves to ``tmp_path`` as well, so a ``config.toml`` in the
    developer's own data root -- where a real hub's TLS settings live -- cannot
    change what these tests observe.
    """
    from src.config import get_settings

    monkeypatch.setenv("VRT_PATHS__DATA_ROOT", str(tmp_path))
    for key in (
        "VRT_HUB__TLS_CERTFILE",
        "VRT_HUB__TLS_KEYFILE",
        "VRT_HUB__ALLOW_INSECURE_HTTP",
    ):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield monkeypatch
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_a_networked_hub_without_a_certificate_refuses_to_start(hub_settings) -> None:
    from src.central_server.server import HubTlsNotConfiguredError, resolve_tls

    with pytest.raises(HubTlsNotConfiguredError, match="generate_hub_certificate"):
        resolve_tls("0.0.0.0")


def test_a_loopback_hub_may_serve_plain_http(hub_settings) -> None:
    from src.central_server.server import resolve_tls

    assert resolve_tls("127.0.0.1") == {}


def test_the_insecure_opt_out_is_explicit(hub_settings) -> None:
    from src.central_server.server import resolve_tls

    hub_settings.setenv("VRT_HUB__ALLOW_INSECURE_HTTP", "true")

    assert resolve_tls("0.0.0.0") == {}


def test_a_configured_certificate_is_served(hub_settings, tmp_path: Path) -> None:
    from src.central_server.server import resolve_tls

    cert, key = tmp_path / "hub-cert.pem", tmp_path / "hub-key.pem"
    cert.write_text("cert")
    key.write_text("key")
    hub_settings.setenv("VRT_HUB__TLS_CERTFILE", str(cert))
    hub_settings.setenv("VRT_HUB__TLS_KEYFILE", str(key))

    assert resolve_tls("0.0.0.0") == {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}


def test_saving_a_plain_http_lan_address_is_refused(tmp_path: Path) -> None:
    """The researcher learns it while typing the address, not from a stuck queue."""
    client = _client(tmp_path, _Unreachable())

    response = client.post(
        "/api/config/central-server", json={"central_server_url": "http://192.168.1.50:9000"}
    )

    assert response.status_code == 400
    assert "insecure_transport_refused" in response.json()["detail"]
    assert client.get("/api/config/central-server").json()["central_server_url"] == ""


def test_generated_certificates_complete_a_verified_handshake(tmp_path: Path) -> None:
    """The tool's output works end to end, in strict X.509 mode, against the CA only."""
    pytest.importorskip("cryptography")
    import importlib.util
    import socket
    import ssl
    import threading

    spec = importlib.util.spec_from_file_location(
        "generate_hub_certificate", REPO_ROOT / "tools" / "generate_hub_certificate.py"
    )
    assert spec and spec.loader
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    paths = tool.generate(["127.0.0.1", "localhost"], tmp_path)

    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(paths["cert"], paths["key"])
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]

    server_errors: list[BaseException] = []

    def serve() -> None:
        # The server answers before either side closes. Without the reply the
        # client could close while the server was still finishing its half of
        # the handshake, which Windows reports as WinError 10053 on the thread.
        try:
            conn, _ = listener.accept()
            with server_ctx.wrap_socket(conn, server_side=True) as tls:
                assert tls.recv(1) == b"x"
                tls.sendall(b"y")
        except BaseException as exc:  # noqa: BLE001 - re-raised on the test thread below
            server_errors.append(exc)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()

    client_ctx = ssl.create_default_context(cafile=str(paths["ca"]))
    client_ctx.verify_flags |= ssl.VERIFY_X509_STRICT
    with (
        socket.create_connection(("127.0.0.1", port)) as raw,
        client_ctx.wrap_socket(raw, server_hostname="127.0.0.1") as tls,
    ):
        assert tls.version() in {"TLSv1.2", "TLSv1.3"}
        tls.sendall(b"x")
        assert tls.recv(1) == b"y"
    thread.join(timeout=5)
    listener.close()
    assert not server_errors, server_errors
