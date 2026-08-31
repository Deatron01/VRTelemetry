"""Tests for typed configuration (VRT-6).

The point of this module is that configuration is now checkable. These tests
cover the three properties that were impossible to assert when it was 18
literals scattered across seven files: paths resolve absolute from one root,
the layering has a defined precedence, and invalid values are rejected at
startup rather than at first use.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config.settings import Settings, get_settings, reset_settings_cache


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """get_settings is cached for the process; tests must not leak into each other."""
    reset_settings_cache()
    yield
    reset_settings_cache()


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #


def test_every_path_hangs_off_one_configurable_root(tmp_path: Path) -> None:
    settings = Settings(paths={"data_root": tmp_path})

    for path in (
        settings.paths.sessions_dir,
        settings.paths.logs_dir,
        settings.paths.appdata_dir,
        settings.paths.metadata_db,
        settings.paths.patients_db,
        settings.paths.usage_db,
        settings.paths.license_cache_db,
        settings.paths.licenses_db,
        settings.paths.central_data_db,
    ):
        assert path.is_absolute()
        assert tmp_path in path.parents


def test_paths_are_absolute_so_behaviour_does_not_depend_on_cwd(tmp_path: Path) -> None:
    """The original defect: "Sessions/" meant a different directory per launch.

    Starting the backend from the repository root and from src/ produced two
    separate databases, each looking empty to the other.
    """
    settings = Settings(paths={"data_root": tmp_path / "nested" / ".." / "nested"})

    assert settings.paths.data_root == (tmp_path / "nested").resolve()
    assert not str(settings.paths.metadata_db).count("..")


def test_the_default_root_is_the_working_directory(tmp_path: Path, monkeypatch) -> None:
    """Existing installs keep finding their existing databases, with no migration.

    Every old literal was relative, so cwd is what they effectively meant.
    """
    monkeypatch.chdir(tmp_path)

    assert Settings().paths.data_root == tmp_path.resolve()


def test_ensure_directories_is_explicit_not_a_side_effect(tmp_path: Path) -> None:
    """Reading configuration must never touch the disk."""
    settings = Settings(paths={"data_root": tmp_path / "fresh"})
    assert not settings.paths.sessions_dir.exists()

    settings.ensure_directories()

    assert settings.paths.sessions_dir.is_dir()
    assert settings.paths.session_logs_dir.is_dir()
    assert settings.paths.appdata_dir.is_dir()


# --------------------------------------------------------------------------- #
# The central server URL
# --------------------------------------------------------------------------- #


def test_there_is_no_default_central_url() -> None:
    """Unset must be distinguishable from configured. It was not, before."""
    assert Settings().central.url is None


def test_requiring_an_unset_url_explains_how_to_set_it() -> None:
    with pytest.raises(RuntimeError, match="VRT_CENTRAL__URL"):
        Settings().require_central_url()


def test_the_old_placeholder_address_is_rejected() -> None:
    """ "http://192.168.1.X:9000" shipped as a live default in two modules.

    It is a note to the reader with a letter where an octet belongs. If it ever
    reappears in a config file or an environment variable, startup fails and
    says why, instead of the app spending every upload on a DNS error.
    """
    with pytest.raises(ValueError, match="placeholder octet"):
        Settings(central={"url": "http://192.168.1.X:9000"})


@pytest.mark.parametrize("bad", ["192.168.1.50:9000", "ftp://host:9000", "just-a-hostname"])
def test_a_url_without_a_scheme_is_rejected(bad: str) -> None:
    with pytest.raises(ValueError, match="http"):
        Settings(central={"url": bad})


def test_a_trailing_slash_is_normalised_away() -> None:
    """Callers concatenate paths onto this; a stray slash yields '//auth/login'."""
    assert Settings(central={"url": "http://10.0.0.9:9000/"}).central.url == "http://10.0.0.9:9000"


# --------------------------------------------------------------------------- #
# Layering and validation
# --------------------------------------------------------------------------- #


def test_environment_variables_override_defaults(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VRT_PATHS__DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("VRT_CENTRAL__URL", "http://10.0.0.9:9000")
    monkeypatch.setenv("VRT_SYNC__INTERVAL_SEC", "5")

    settings = Settings()

    assert settings.paths.data_root == tmp_path.resolve()
    assert settings.central.url == "http://10.0.0.9:9000"
    assert settings.sync.interval_sec == 5


def test_an_explicit_argument_beats_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("VRT_CENTRAL__URL", "http://from-env:9000")

    assert Settings(central={"url": "http://explicit:9000"}).central.url == "http://explicit:9000"


def test_a_config_file_in_the_data_root_is_read(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "config.toml").write_text(
        '[central]\nurl = "http://from-file:9000"\n[sync]\ninterval_sec = 45\n'
    )
    monkeypatch.chdir(tmp_path)

    settings = get_settings()

    assert settings.central.url == "http://from-file:9000"
    assert settings.sync.interval_sec == 45


def test_a_malformed_config_file_fails_loudly(tmp_path: Path, monkeypatch) -> None:
    """Falling back to defaults because of a typo is how an install quietly
    starts writing to the wrong directory."""
    (tmp_path / "config.toml").write_text("this is not = valid = toml\n")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="not valid TOML"):
        get_settings()


@pytest.mark.parametrize(
    ("section", "values"),
    [
        ("api", {"port": 0}),
        ("api", {"port": 70000}),
        ("sync", {"interval_sec": 0}),
        ("sync", {"interval_sec": -1}),
        ("acquisition", {"default_max_sampling_hz": 0}),
        ("central", {"timeout_sec": 0}),
    ],
)
def test_out_of_range_values_are_rejected_at_startup(section: str, values: dict) -> None:
    with pytest.raises(ValueError):
        Settings(**{section: values})


def test_an_unknown_key_is_rejected_rather_than_ignored() -> None:
    """A typo'd key that is silently dropped is a setting that never applied."""
    with pytest.raises(ValueError):
        Settings(pathz={"data_root": "/tmp"})


def test_the_api_and_hub_cannot_share_a_port() -> None:
    """Both legitimately run on one machine in development; a collision shows
    up as one of them silently failing to bind."""
    with pytest.raises(ValueError, match="both configured"):
        Settings(api={"host": "0.0.0.0", "port": 9000}, hub={"host": "0.0.0.0", "port": 9000})


def test_get_settings_is_cached_within_a_process(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert get_settings() is get_settings()

    reset_settings_cache()
    assert get_settings() is not None
