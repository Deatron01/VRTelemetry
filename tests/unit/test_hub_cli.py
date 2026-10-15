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


def test_setup_writes_the_scheduled_task_schtasks_reads(data_root: Path) -> None:
    import xml.etree.ElementTree as ET

    _setup(data_root)

    raw = (data_root / cli.TASK_XML_NAME).read_bytes()
    assert raw[:2] == b"\xff\xfe", "schtasks /XML reads UTF-16; a UTF-8 file is 'malformed'"
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    root = ET.fromstring(raw.decode("utf-16"))  # noqa: S314 - our own output

    exec_ = root.find("t:Actions/t:Exec", ns)
    assert exec_ is not None
    assert exec_.findtext("t:Arguments", namespaces=ns) == (
        f'--data-root "{data_root.resolve()}" serve'
    )
    assert exec_.findtext("t:WorkingDirectory", namespaces=ns) == str(data_root.resolve())
    assert root.findtext("t:Principals/t:Principal/t:UserId", namespaces=ns) == "S-1-5-18"
    assert root.findtext("t:Settings/t:ExecutionTimeLimit", namespaces=ns) == "PT0S"
    assert root.find("t:Settings/t:RestartOnFailure", ns) is not None
    assert root.find("t:Triggers/t:BootTrigger", ns) is not None


def test_task_xml_escapes_paths() -> None:
    xml = cli.task_xml(Path(r"C:\R&D\hub.exe"), Path(r"C:\R&D\data"))

    assert r"C:\R&amp;D\hub.exe" in xml
    assert "R&D" not in xml
