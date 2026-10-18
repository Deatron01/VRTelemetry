"""Writing ``hub-ca.pem`` and ``[central]`` into a workstation's data root.

Shared by the hub's installer, pairing, and same-machine kit adoption, so the
format is pinned once here. The case that matters most is the existing
``config.toml``: it may hold a lab's consent configuration, and the kit's own
instructions say to merge the ``[central]`` block into it, not to replace it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.config import CentralServerSettings
from src.config.workstation_kit import (
    KitMergeError,
    install_workstation_kit,
    merge_central_block,
    workstation_config_toml,
)

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

URL = "https://192.168.1.50:9000"
PEM = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"


def test_a_fresh_config_is_the_kit_format() -> None:
    text = workstation_config_toml(URL)

    assert tomllib.loads(text) == {"central": {"url": URL, "ca_bundle": "hub-ca.pem"}}


def test_the_hub_cli_writes_the_same_format() -> None:
    from src.central_server import cli

    assert cli.workstation_config_toml(URL) == workstation_config_toml(URL)


def test_merging_appends_central_and_keeps_everything_else() -> None:
    existing = '# our lab\'s settings\n[consent]\nlaboratory_name = "Vision Lab"  # keep me\n'

    merged = merge_central_block(existing, URL)

    assert merged.startswith(existing)
    parsed = tomllib.loads(merged)
    assert parsed["consent"] == {"laboratory_name": "Vision Lab"}
    assert parsed["central"] == {"url": URL, "ca_bundle": "hub-ca.pem"}


def test_merging_replaces_url_and_keeps_other_central_keys() -> None:
    existing = (
        '[central]\nurl = "https://old-hub:9000"\ntimeout_sec = 30\n\n[consent]\nstudy_id = "s1"\n'
    )

    merged = merge_central_block(existing, URL)

    parsed = tomllib.loads(merged)
    assert parsed["central"] == {"url": URL, "timeout_sec": 30, "ca_bundle": "hub-ca.pem"}
    assert parsed["consent"] == {"study_id": "s1"}
    assert "\n\n[consent]" in merged, "the blank line before the next table is kept"


def test_an_absolute_windows_path_is_escaped() -> None:
    merged = merge_central_block("", URL, r"C:\Users\lab\data\hub-ca.pem")

    assert tomllib.loads(merged)["central"]["ca_bundle"] == r"C:\Users\lab\data\hub-ca.pem"


@pytest.mark.parametrize(
    "existing",
    [
        "[central\nurl = 1\n",  # not TOML at all
        'central = { url = "https://old:9000" }\n',  # inline table
        'central.url = "https://old:9000"\n',  # dotted keys
    ],
)
def test_a_file_that_cannot_be_merged_safely_is_refused(existing: str) -> None:
    with pytest.raises(KitMergeError):
        merge_central_block(existing, URL)


def test_install_creates_both_files(tmp_path: Path) -> None:
    result = install_workstation_kit(tmp_path, URL, PEM)

    assert result.merged is False
    assert (tmp_path / "hub-ca.pem").read_text(encoding="ascii") == PEM
    assert (
        tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))["central"]["url"]
        == URL
    )


def test_install_merges_into_an_existing_config(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text('[consent]\nstudy_id = "s1"\n', encoding="utf-8")

    result = install_workstation_kit(
        tmp_path, URL, PEM, ca_bundle=(tmp_path / "hub-ca.pem").as_posix()
    )

    assert result.merged is True
    parsed = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert parsed["consent"] == {"study_id": "s1"}
    # What the workstation will load at its next start.
    central = CentralServerSettings(**parsed["central"])
    assert central.url == URL
    assert central.ca_bundle == (tmp_path / "hub-ca.pem").resolve()


def test_install_writes_nothing_when_the_config_cannot_be_merged(tmp_path: Path) -> None:
    original = 'central = { url = "https://old:9000" }\n'
    (tmp_path / "config.toml").write_text(original, encoding="utf-8")

    with pytest.raises(KitMergeError):
        install_workstation_kit(tmp_path, URL, PEM)

    assert not (tmp_path / "hub-ca.pem").exists()
    assert (tmp_path / "config.toml").read_text(encoding="utf-8") == original


def test_install_refuses_something_that_is_not_a_certificate(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        install_workstation_kit(tmp_path, URL, b"not a certificate")
    assert list(tmp_path.iterdir()) == []
