"""Pairing a workstation with a hub on another machine, end to end.

The workstation's ``POST /api/config/central-server/pair`` runs against the
hub's real pairing routes, joined by a bridge that stands in for the network:
the workstation's HTTP client hands each request to a TestClient over the hub
app. What is checked is what a researcher would see -- the route's answer --
and what is left on disk: ``hub-ca.pem`` and the ``[central]`` block.

The hub app here is the pairing router plus a ``/health`` route, not
``src.central_server.server``: importing that initialises two databases at
module scope (VRT-15), which is why the router is built separately.
"""

from __future__ import annotations

import ssl
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("cryptography")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.central_server import certificates
from src.central_server.pairing import PairingService, build_router
from src.config import PathSettings, Settings
from src.config.settings import _load_config_file
from src.interfaces.api.app import create_app
from src.interfaces.api.container import build_container

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

HUB = "https://192.168.1.50:9000"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class NetworkBridge:
    """The workstation's view of the LAN: every request goes to the hub app."""

    def __init__(self, hub: TestClient) -> None:
        import requests

        self.RequestException = requests.RequestException
        self._hub = hub
        self.calls: list[tuple[str, str, Any]] = []

    def _send(self, method: str, url: str, **kwargs: Any) -> Any:
        path = urlsplit(url).path
        self.calls.append((method, path, kwargs.get("verify")))
        return self._hub.request(method, path, json=kwargs.get("json"))

    def get(self, url: str, **kwargs: Any) -> Any:
        return self._send("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Any:
        return self._send("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> Any:
        return self._send("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Any:
        return self._send("DELETE", url, **kwargs)


@pytest.fixture(scope="module")
def ca_pem(tmp_path_factory: pytest.TempPathFactory) -> str:
    paths = certificates.generate(["192.168.1.50"], tmp_path_factory.mktemp("tls"))
    return paths["ca"].read_text(encoding="ascii")


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def make_hub(ca_pem: str, clock: FakeClock, **limits: Any) -> TestClient:
    service = PairingService(lambda: ca_pem, clock=clock, **limits)
    app = FastAPI()
    app.include_router(build_router(service, lambda: {"email": "admin@lab", "role": "admin"}))
    app.get("/health")(lambda: {"ok": True, "service": "vrtelemetry-hub"})
    return TestClient(app)


@pytest.fixture
def hub(ca_pem: str, clock: FakeClock) -> TestClient:
    return make_hub(ca_pem, clock)


def make_workstation(data_root: Path, hub: TestClient) -> tuple[TestClient, NetworkBridge, Any]:
    bridge = NetworkBridge(hub)
    container = build_container(Settings(paths=PathSettings(data_root=data_root)), http=bridge)
    return TestClient(create_app(container)), bridge, container


def issue_code(hub: TestClient) -> str:
    response = hub.post("/admin/pairing/code")
    assert response.status_code == 200, response.text
    return response.json()["code"]


def pair(workstation: TestClient, code: str) -> Any:
    return workstation.post(
        "/api/config/central-server/pair", json={"central_server_url": HUB, "code": code}
    )


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 10**6:06d}"


def test_a_valid_code_installs_the_hub_ca_and_address(
    tmp_path: Path, hub: TestClient, ca_pem: str
) -> None:
    workstation, bridge, container = make_workstation(tmp_path, hub)
    issued = hub.post("/admin/pairing/code").json()

    response = pair(workstation, issued["code"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["url"] == HUB
    assert body["fingerprint"] == issued["ca_fingerprint"], (
        "the workstation shows the same fingerprint the admin UI does"
    )
    assert body["merged_existing_config"] is False

    written = (tmp_path / "hub-ca.pem").read_text(encoding="ascii")
    assert ssl.PEM_cert_to_DER_cert(written) == ssl.PEM_cert_to_DER_cert(ca_pem)

    # What the workstation loads at its next start.
    loaded = Settings(paths=PathSettings(data_root=tmp_path), **_load_config_file(tmp_path))
    assert loaded.central.url == HUB
    assert loaded.central.ca_bundle == (tmp_path / "hub-ca.pem").resolve()

    # And what it uses right away, without a restart.
    assert workstation.get("/api/config/central-server").json() == {"central_server_url": HUB}
    assert container.central_url() == HUB

    # Only the first request goes out unverified; the rest are checked against
    # the certificate the hub has just proved is its own.
    assert [(m, p) for m, p, _ in bridge.calls] == [
        ("POST", "/pairing/start"),
        ("GET", "/health"),
        ("POST", "/pairing/finish"),
    ]
    assert bridge.calls[0][2] is False
    assert all(verify not in (None, False) for _, _, verify in bridge.calls[1:])

    assert hub.get("/admin/pairing/code").json()["state"] == "used"


def test_an_existing_config_is_merged_not_replaced(tmp_path: Path, hub: TestClient) -> None:
    (tmp_path / "config.toml").write_text(
        '# lab settings\n[consent]\nlaboratory_name = "Vision Lab"\n\n'
        '[central]\nurl = "https://old-hub:9000"\ntimeout_sec = 20\n',
        encoding="utf-8",
    )
    workstation, _, _ = make_workstation(tmp_path, hub)

    response = pair(workstation, issue_code(hub))

    assert response.status_code == 200, response.text
    assert response.json()["merged_existing_config"] is True
    text = (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert text.startswith("# lab settings\n")
    parsed = tomllib.loads(text)
    assert parsed["consent"] == {"laboratory_name": "Vision Lab"}
    assert parsed["central"]["url"] == HUB
    assert parsed["central"]["timeout_sec"] == 20
    assert parsed["central"]["ca_bundle"]


def test_a_wrong_code_writes_nothing(tmp_path: Path, hub: TestClient) -> None:
    workstation, bridge, _ = make_workstation(tmp_path, hub)
    code = issue_code(hub)

    response = pair(workstation, wrong(code))

    assert response.status_code == 400
    assert response.json()["detail"]["reason"] == "code_rejected"
    assert not (tmp_path / "hub-ca.pem").exists()
    assert not (tmp_path / "config.toml").exists()
    assert [p for _, p, _ in bridge.calls] == ["/pairing/start"], (
        "nothing from an unconfirmed reply is used, not even for a health check"
    )
    # The researcher retypes it correctly; a typo does not burn the code.
    assert pair(workstation, code).status_code == 200


def test_an_expired_code_is_refused(tmp_path: Path, hub: TestClient, clock: FakeClock) -> None:
    workstation, _, _ = make_workstation(tmp_path, hub)
    code = issue_code(hub)
    clock.now += 11 * 60

    response = pair(workstation, code)

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "pairing_code_expired"
    assert not (tmp_path / "hub-ca.pem").exists()


def test_a_used_code_cannot_pair_a_second_workstation(tmp_path: Path, hub: TestClient) -> None:
    code = issue_code(hub)
    first, _, _ = make_workstation(tmp_path / "first", hub)
    second, _, _ = make_workstation(tmp_path / "second", hub)

    assert pair(first, code).status_code == 200
    response = pair(second, code)

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "pairing_code_used"
    assert not (tmp_path / "second" / "hub-ca.pem").exists()


def test_repeated_attempts_are_rate_limited(tmp_path: Path, ca_pem: str, clock: FakeClock) -> None:
    hub = make_hub(ca_pem, clock, rate_per_address=3, max_attempts=100)
    workstation, _, _ = make_workstation(tmp_path, hub)
    code = issue_code(hub)
    for _ in range(3):
        assert pair(workstation, wrong(code)).status_code == 400

    response = pair(workstation, code)

    assert response.status_code == 429
    assert response.json()["detail"]["reason"] == "rate_limited"
    assert not (tmp_path / "hub-ca.pem").exists()

    clock.now += 61
    assert pair(workstation, code).status_code == 200


def test_a_hub_that_issued_no_code_says_so(tmp_path: Path, hub: TestClient) -> None:
    workstation, _, _ = make_workstation(tmp_path, hub)

    response = pair(workstation, "123456")

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "no_pairing_code"


def test_plain_http_addresses_are_refused_before_anything_is_sent(
    tmp_path: Path, hub: TestClient
) -> None:
    workstation, bridge, _ = make_workstation(tmp_path, hub)

    response = workstation.post(
        "/api/config/central-server/pair",
        json={"central_server_url": "http://192.168.1.50:9000", "code": "123456"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["reason"] == "https_required"
    assert bridge.calls == []


def test_the_real_hub_serves_the_pairing_routes(tmp_path: Path, child_env) -> None:
    """``server.py`` mounts the router -- checked in a clean interpreter (VRT-15).

    Read from the OpenAPI document: ``app.routes`` holds an included router as
    one opaque entry on current FastAPI.
    """
    import json
    import subprocess

    repo_root = Path(__file__).resolve().parents[2]
    source = (
        "import json, sys;"
        f"sys.path.insert(0, {str(repo_root)!r});"
        "from src.central_server.server import app, hub_ca_path;"
        "paths = app.openapi()['paths'];"
        "routes = sorted((m.upper(), p) for p, ops in paths.items() for m in ops);"
        "print(json.dumps({'routes': routes, 'ca': str(hub_ca_path())}))"
    )
    result = subprocess.run(  # noqa: S603 - the argv is this file's own literal
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        env=child_env(drop_prefix="VRT_", VRT_PATHS__DATA_ROOT=str(tmp_path)),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    routes = {tuple(r) for r in report["routes"]}

    assert {
        ("POST", "/admin/pairing/code"),
        ("GET", "/admin/pairing/code"),
        ("DELETE", "/admin/pairing/code"),
        ("POST", "/pairing/start"),
        ("POST", "/pairing/finish"),
    } <= routes
    assert Path(report["ca"]) == tmp_path / "CentralServer" / "tls" / "hub-ca.pem"
