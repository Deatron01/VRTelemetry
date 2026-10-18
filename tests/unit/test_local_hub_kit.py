# tests/unit/test_local_hub_kit.py
"""A workstation on the hub's own machine configures itself from the hub's kit.

The hub installer writes a workstation kit -- ``hub-ca.pem`` and a two-line
``config.toml`` -- to ``%ProgramData%\\VRTelemetryHub\\workstation-kit``, readable
by every user and writable only by Administrators. Copying those two files into
the desktop app's data root by hand was the one setup step left when hub and
workstation share a PC, and nothing in it needs a person: the files are already
on the machine, and only an administrator could have put them there.

The rule these tests pin: adopt the kit **only when nothing else names a hub**.
An address in ``config.toml``, the environment, or the researcher's own saved
setting always wins, and so does an explicit ``ca_bundle`` -- the kit fills a
gap, it never overrides a choice.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.central_server.cli import write_workstation_kit
from src.config import CentralServerSettings, Settings
from src.config.settings import _load_config_file
from src.storage.local_hub_kit import adopt_local_hub_kit

KIT_URL = "https://192.168.1.50:9000"
CA_PEM = "-----BEGIN CERTIFICATE-----\nlocal hub ca\n-----END CERTIFICATE-----\n"


@pytest.fixture
def kit_dir(tmp_path: Path) -> Path:
    """A kit exactly as the hub's ``setup`` writes it."""
    ca_file = tmp_path / "hub-tls" / "hub-ca.pem"
    ca_file.parent.mkdir()
    ca_file.write_text(CA_PEM, encoding="utf-8")
    return write_workstation_kit(tmp_path / "workstation-kit", KIT_URL, ca_file)


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The desktop app's data root, which is also the backend's working directory.

    ``ca_bundle = "hub-ca.pem"`` is relative, and the settings validator resolves
    it against the working directory -- so the tests run from the data root,
    as the packaged backend does.
    """
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.chdir(root)
    return root


def _unconfigured() -> CentralServerSettings:
    return CentralServerSettings(url=None, ca_bundle=None)


def _central_after(data_root: Path) -> CentralServerSettings:
    """The hub settings a freshly started backend would now resolve."""
    return Settings(**_load_config_file(data_root)).central


def test_unconfigured_workstation_adopts_the_kit(kit_dir: Path, data_root: Path) -> None:
    adopted = adopt_local_hub_kit(data_root, _unconfigured(), saved_url=None, kit_dir=kit_dir)

    assert adopted == KIT_URL
    assert (data_root / "hub-ca.pem").read_text(encoding="utf-8") == CA_PEM
    central = _central_after(data_root)
    assert central.url == KIT_URL
    assert central.ca_bundle == (data_root / "hub-ca.pem").resolve()


def test_no_kit_on_this_machine_changes_nothing(tmp_path: Path, data_root: Path) -> None:
    adopted = adopt_local_hub_kit(
        data_root, _unconfigured(), saved_url=None, kit_dir=tmp_path / "missing"
    )

    assert adopted is None
    assert list(data_root.iterdir()) == []


def test_a_configured_address_wins(kit_dir: Path, data_root: Path) -> None:
    config = data_root / "config.toml"
    config.write_text('[central]\nurl = "https://10.0.0.7:9000"\n', encoding="utf-8")
    central = CentralServerSettings(url="https://10.0.0.7:9000")

    adopted = adopt_local_hub_kit(data_root, central, saved_url=None, kit_dir=kit_dir)

    assert adopted is None
    assert config.read_text(encoding="utf-8") == '[central]\nurl = "https://10.0.0.7:9000"\n'
    assert not (data_root / "hub-ca.pem").exists()


def test_an_explicit_ca_bundle_wins(kit_dir: Path, data_root: Path) -> None:
    own_ca = data_root / "lab-ca.pem"
    own_ca.write_text(CA_PEM, encoding="utf-8")

    adopted = adopt_local_hub_kit(
        data_root, CentralServerSettings(ca_bundle=own_ca), saved_url=None, kit_dir=kit_dir
    )

    assert adopted is None
    assert not (data_root / "config.toml").exists()


def test_a_different_saved_address_wins(kit_dir: Path, data_root: Path) -> None:
    """The researcher typed another hub into the app: the local kit would
    point ``ca_bundle`` at the wrong CA and break that connection."""
    adopted = adopt_local_hub_kit(
        data_root, _unconfigured(), saved_url="https://10.0.0.7:9000", kit_dir=kit_dir
    )

    assert adopted is None
    assert not (data_root / "config.toml").exists()


def test_the_same_saved_address_still_gets_the_certificate(kit_dir: Path, data_root: Path) -> None:
    """Typing the local hub's address without its CA is the half-done setup
    this exists to finish."""
    adopted = adopt_local_hub_kit(
        data_root, _unconfigured(), saved_url=KIT_URL + "/", kit_dir=kit_dir
    )

    assert adopted == KIT_URL
    assert _central_after(data_root).ca_bundle == (data_root / "hub-ca.pem").resolve()


def test_an_existing_config_keeps_its_other_settings(kit_dir: Path, data_root: Path) -> None:
    (data_root / "config.toml").write_text("[sync]\ninterval_sec = 45\n", encoding="utf-8")

    adopt_local_hub_kit(data_root, _unconfigured(), saved_url=None, kit_dir=kit_dir)

    values = _load_config_file(data_root)
    assert values["sync"]["interval_sec"] == 45
    assert values["central"]["url"] == KIT_URL


def test_an_existing_central_block_is_extended_not_duplicated(
    kit_dir: Path, data_root: Path
) -> None:
    """A second ``[central]`` header would make the whole file invalid TOML,
    and the backend refuses to start on an invalid config."""
    (data_root / "config.toml").write_text(
        "# lab settings\n[central]\ntimeout_sec = 20\n\n[sync]\ninterval_sec = 45\n",
        encoding="utf-8",
    )

    adopt_local_hub_kit(data_root, _unconfigured(), saved_url=None, kit_dir=kit_dir)

    values = _load_config_file(data_root)
    assert values["central"] == {"timeout_sec": 20, "url": KIT_URL, "ca_bundle": "hub-ca.pem"}
    assert values["sync"]["interval_sec"] == 45


def test_a_central_table_it_cannot_safely_edit_is_left_alone(
    kit_dir: Path, data_root: Path
) -> None:
    """Dotted keys define the table without a ``[central]`` header to insert under."""
    original = "central.timeout_sec = 20\n"
    (data_root / "config.toml").write_text(original, encoding="utf-8")

    adopted = adopt_local_hub_kit(data_root, _unconfigured(), saved_url=None, kit_dir=kit_dir)

    assert adopted is None
    assert (data_root / "config.toml").read_text(encoding="utf-8") == original
    assert not (data_root / "hub-ca.pem").exists()


def test_a_kit_without_an_address_is_ignored(kit_dir: Path, data_root: Path) -> None:
    (kit_dir / "config.toml").write_text("[central]\n", encoding="utf-8")

    adopted = adopt_local_hub_kit(data_root, _unconfigured(), saved_url=None, kit_dir=kit_dir)

    assert adopted is None
    assert list(data_root.iterdir()) == []


def test_the_backend_adopts_the_kit_before_reading_settings(
    kit_dir: Path, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``boot_server_context`` is what the packaged desktop app runs."""
    import src.server_entrypoint as entrypoint
    from src.config import get_settings, reset_settings_cache
    from src.storage import local_hub_kit

    monkeypatch.delenv("VRT_CENTRAL__URL", raising=False)
    monkeypatch.delenv("VRT_CENTRAL__CA_BUNDLE", raising=False)
    monkeypatch.setenv("VRT_PATHS__DATA_ROOT", str(data_root))
    monkeypatch.setattr(local_hub_kit, "DEFAULT_KIT_DIR", kit_dir)
    served: list[str | None] = []
    monkeypatch.setattr(entrypoint, "create_app", lambda: object())

    def fake_run(*_args: object, **_kwargs: object) -> None:
        served.append(get_settings().central.url)

    monkeypatch.setattr(entrypoint.uvicorn, "run", fake_run)
    reset_settings_cache()
    try:
        entrypoint.boot_server_context()
    finally:
        reset_settings_cache()

    assert served == [KIT_URL]
