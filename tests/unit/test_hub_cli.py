"""The installed hub's command line: what the Windows installer runs.

``setup`` runs on every install and upgrade, so the properties that matter are
that its output loads as real settings and that a second run changes nothing a
lab may have edited.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from src.central_server import cli
from src.config import Settings
from src.config.settings import CentralServerSettings, _load_config_file


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # main() changes directory and sets the data-root variable; monkeypatch
    # puts both back so no other test inherits them.
    monkeypatch.chdir(tmp_path)
    # setenv first so monkeypatch records the original state and restores it,
    # even though main() sets the variable again.
    monkeypatch.setenv("VRT_PATHS__DATA_ROOT", "")
    monkeypatch.delenv("VRT_PATHS__DATA_ROOT")
    return tmp_path / "hub"


def _setup(data_root: Path, *extra: str) -> int:
    return cli.main(["--data-root", str(data_root), "setup", "--address", "192.168.10.5", *extra])


def test_setup_writes_a_config_the_hub_loads(data_root: Path) -> None:
    assert _setup(data_root, "--port", "9100") == 0

    values = _load_config_file(data_root)
    hub = Settings(**values).hub

    assert hub.port == 9100
    assert hub.host == "0.0.0.0"
    assert hub.tls_certfile is not None and hub.tls_certfile.is_file()
    assert hub.tls_keyfile is not None and hub.tls_keyfile.is_file()


def test_setup_keeps_what_a_lab_edited(data_root: Path) -> None:
    _setup(data_root)
    config = data_root / "config.toml"
    config.write_text(config.read_text(encoding="utf-8") + "# edited by the lab\n", "utf-8")
    key = data_root / "CentralServer" / "tls" / "hub-key.pem"
    key_before = key.read_bytes()

    assert _setup(data_root) == 0

    assert config.read_text(encoding="utf-8").endswith("# edited by the lab\n")
    assert key.read_bytes() == key_before, "reinstalling must not replace the certificate"


def test_the_workstation_kit_is_a_working_client_config(
    data_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(data_root, "--port", "9000")
    kit = data_root / cli.KIT_DIR_NAME

    # Copied into a client's data root, which is where the desktop app starts
    # its backend -- so the relative ca_bundle must resolve there.
    client_root = tmp_path / "client-data"
    client_root.mkdir()
    for name in ("hub-ca.pem", "config.toml"):
        (client_root / name).write_bytes((kit / name).read_bytes())
    monkeypatch.chdir(client_root)

    values = _load_config_file(client_root)
    central = CentralServerSettings(**values["central"])

    assert central.url == "https://192.168.10.5:9000"
    assert central.ca_bundle == client_root / "hub-ca.pem"
    assert (kit / "README.txt").is_file()
    assert not (kit / "hub-ca-key.pem").exists(), "the CA key must never leave the hub"
    assert not (kit / "hub-key.pem").exists()


def test_data_root_is_entered_before_settings_are_read(data_root: Path) -> None:
    _setup(data_root)

    assert Path.cwd() == data_root.resolve()
    assert os.environ["VRT_PATHS__DATA_ROOT"] == str(data_root.resolve())


def test_subcommand_arguments_reach_the_tool(
    data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr("src.central_server.certificates.main", lambda argv: seen.append(argv) or 0)

    assert cli.main(["--data-root", str(data_root), "gen-cert", "--host", "10.0.0.1"]) == 0
    assert seen == [["--host", "10.0.0.1"]]


def test_an_unknown_argument_is_refused(data_root: Path) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--data-root", str(data_root), "serve", "--bogus"])


def test_setup_registers_nothing_to_start_with_windows(data_root: Path) -> None:
    """The hub runs when someone starts it, not at boot.

    1.2.0 and earlier wrote a Task Scheduler definition here -- start at boot as
    SYSTEM, restart after a crash -- and Defender's behaviour heuristics flagged
    the unsigned installer that registered it as persistence malware. A lab hub
    that is started by hand needs none of it.
    """
    _setup(data_root)

    assert not (data_root / "hub-task.xml").exists()
    assert not hasattr(cli, "task_xml")
