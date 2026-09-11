# src/config/settings.py
"""One place where every path, URL, port and interval is decided (VRT-6).

Before this module, configuration was 18 string literals spread across seven
files as default arguments::

    def __init__(self, db_path: str = "Sessions/vr_metadata.db"): ...
    def __init__(self, db_path: str = "LicenseServer/licenses.db"): ...
    def __init__(self, db_path: str = "AppData/license_cache.db"): ...
    central_server_url: str = "http://192.168.1.X:9000"

Three problems with that, in ascending order of seriousness.

*It was unfindable.* Changing where the data lives meant knowing all seven
places. There is also a ``config.json`` at the repository root; it is zero
bytes and nothing reads it.

*It was relative to the process working directory.* ``Sessions/`` means "a
directory called Sessions, wherever you happened to launch from". Start the
backend from the repository root and from ``src/`` and you get two separate
databases, each looking empty to the other. Paths here resolve to absolute
under a single configurable data root.

*One of the defaults was a placeholder.* ``http://192.168.1.X:9000`` is not an
address; it is a note to the reader. It shipped as a live default in two
places, which means the failure mode for "nobody configured the server" was a
DNS error rather than a message telling you to configure the server. There is
now no default at all: unset means the application says it is unset.

Precedence, lowest to highest:

1. the defaults in this file
2. ``config.toml`` in the data root, if present
3. environment variables, prefixed ``VRT_`` with ``__`` between levels --
   ``VRT_PATHS__DATA_ROOT``, ``VRT_CENTRAL__URL``, ``VRT_SYNC__INTERVAL_SEC``
4. explicit arguments at the call site

Anything invalid fails at startup, naming the field, rather than at first use.

**On the accessor.** :func:`get_settings` is a cached module-level function,
which is a service locator, and a composition root that constructs Settings
once and passes it down would be better. That composition root does not exist
yet -- ``src/main.py`` builds eleven singletons at import time, and untangling
that is VRT-12. Introducing settings first and injecting them properly second
is the order that keeps every step shippable. When VRT-12 lands, the accessor
goes and the constructors keep the ``| None`` parameters they already have.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on the 3.10 leg of the CI matrix
    # tomllib is stdlib from 3.11. This project supports 3.10, where importing
    # it raises ModuleNotFoundError at startup -- caught by mypy running against
    # python_version 3.10, not by any test on a 3.11+ developer machine.
    import tomli as tomllib
from pydantic_settings import BaseSettings, SettingsConfigDict


class PathSettings(BaseSettings):
    """Where this installation keeps its data.

    Every path is resolved absolute against :attr:`data_root`, so behaviour no
    longer depends on the directory the process was launched from.
    """

    #: Root for all runtime data. Defaults to the current working directory,
    #: which is what every relative literal effectively meant before -- so an
    #: existing install keeps finding its existing databases with no migration.
    #: Set VRT_PATHS__DATA_ROOT to pin it.
    data_root: Path = Field(default_factory=Path.cwd)

    sessions_dir_name: str = "Sessions"
    logs_dir_name: str = "Logs"
    appdata_dir_name: str = "AppData"
    license_dir_name: str = "LicenseServer"
    central_dir_name: str = "CentralServer"

    @field_validator("data_root")
    @classmethod
    def _absolute(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    # --- directories -------------------------------------------------------

    @property
    def sessions_dir(self) -> Path:
        """Recorded Parquet frames and the local metadata databases."""
        return self.data_root / self.sessions_dir_name

    @property
    def session_logs_dir(self) -> Path:
        """Per-session diagnostic logs, uploaded alongside the session."""
        return self.sessions_dir / "logs"

    @property
    def logs_dir(self) -> Path:
        """The rolling engine log."""
        return self.data_root / self.logs_dir_name

    @property
    def appdata_dir(self) -> Path:
        """Workstation-local state: the licence cache and account session."""
        return self.data_root / self.appdata_dir_name

    @property
    def license_dir(self) -> Path:
        """Central hub only: the licence database lives here."""
        return self.data_root / self.license_dir_name

    @property
    def central_dir(self) -> Path:
        """Central hub only: ingested sessions and their metadata."""
        return self.data_root / self.central_dir_name

    # --- databases ---------------------------------------------------------

    @property
    def metadata_db(self) -> Path:
        return self.sessions_dir / "vr_metadata.db"

    @property
    def patients_db(self) -> Path:
        return self.sessions_dir / "patients.db"

    @property
    def usage_db(self) -> Path:
        return self.sessions_dir / "usage_telemetry.db"

    @property
    def license_cache_db(self) -> Path:
        return self.appdata_dir / "license_cache.db"

    @property
    def licenses_db(self) -> Path:
        return self.license_dir / "licenses.db"

    @property
    def central_data_db(self) -> Path:
        return self.central_dir / "central_data.db"

    @property
    def central_storage_dir(self) -> Path:
        return self.central_dir / "CentralStorage"


class CentralServerSettings(BaseSettings):
    """How this workstation reaches the central hub."""

    #: No default on purpose. The old placeholder "http://192.168.1.X:9000"
    #: shipped as a live value, so an unconfigured install failed with a DNS
    #: error instead of saying it was unconfigured. None means unset, and
    #: callers report that plainly.
    url: str | None = None

    #: Seconds. Applied to every request to the hub. Short by design: the hub
    #: is a LAN service and every call to it is best-effort, so a slow server
    #: must never stall a recording.
    timeout_sec: float = Field(default=10.0, gt=0, le=120)

    #: PEM file holding the certificate authority that signed the hub's TLS
    #: certificate (GDPR-01). Needed when the hub uses a certificate from its
    #: own small CA -- which ``tools/generate_hub_certificate.py`` creates --
    #: rather than one a public CA issued. None means the operating system's
    #: normal trust store, which is right for a publicly-issued certificate.
    ca_bundle: Path | None = None

    #: Development escape hatch, and nothing else (GDPR-01). Participant data
    #: and eye-tracking telemetry are refused over plain ``http://`` to any
    #: host but this machine's own loopback. Set this only on a disposable test
    #: setup; the application logs a warning for every request it lets through.
    allow_insecure_http: bool = False

    @field_validator("ca_bundle")
    @classmethod
    def _ca_bundle_exists(cls, value: Path | None) -> Path | None:
        """Fail at startup, naming the file, rather than on the first upload.

        ``requests`` reports a missing bundle as an ``OSError`` raised from
        inside the adapter -- not a ``RequestException`` -- so every client's
        "hub unreachable" handling would miss it and the upload path would
        crash instead of queueing.
        """
        if value is None:
            return None
        value = value.expanduser().resolve()
        if not value.is_file():
            raise ValueError(f"central.ca_bundle {value} does not exist or is not a file")
        return value

    @field_validator("url")
    @classmethod
    def _looks_like_a_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError(f"must start with http:// or https:// (got {value!r})")
        if ".X:" in value or value.endswith(".X"):
            raise ValueError(
                f"{value!r} still contains the placeholder octet 'X' -- set a real address"
            )
        return value


class ApiSettings(BaseSettings):
    """The workstation's own HTTP API, spawned by the Electron shell."""

    #: Loopback, deliberately. Only the local Electron app calls this, and it
    #: holds patient records; there is no reason for it to be reachable from
    #: the network.
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    #: CORS. The Vite dev server and the packaged app, and nothing else.
    #:
    #: The original value was ``["*"]`` with ``allow_credentials=True``, a
    #: combination browsers reject outright -- over-permissive in intent and
    #: non-functional in practice.
    #:
    #: ``"null"`` is deliberately **not** here, and must not be added. A
    #: ``file://`` page has the origin ``null``, so allowing it would make the
    #: packaged app work -- and would also let *any* website reach this API
    #: through a sandboxed iframe, which shares that same origin. This API binds
    #: loopback, but loopback is reachable from the browser of the person
    #: sitting at the machine; it serves patient records and can start and stop
    #: recordings. See electron/main.js, which registers the ``app://`` scheme
    #: so the packaged renderer has a real origin of its own.
    allowed_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "app://.",
    )

    #: Methods the frontend actually uses. ``["*"]`` was the previous value; a
    #: narrower list is not much of a control on its own, but it means adding a
    #: verb to the API is a decision rather than a side effect.
    allowed_methods: tuple[str, ...] = ("GET", "POST", "PUT", "DELETE", "OPTIONS")

    #: Request headers the frontend actually sends. Same reasoning.
    allowed_headers: tuple[str, ...] = ("Content-Type",)


class HubSettings(BaseSettings):
    """The central hub service, when this process is the hub."""

    #: All interfaces: unlike the workstation API, other machines must reach
    #: this one. Narrow it to a specific interface in deployment if you can.
    host: str = "0.0.0.0"  # noqa: S104 - LAN service by design
    port: int = Field(default=9000, ge=1, le=65535)

    #: Heartbeats older than this mark a client offline in the admin view.
    #: Three times the client's 30 s ping gives room for a blip.
    client_online_threshold_sec: int = Field(default=90, gt=0)

    #: TLS certificate and private key, both PEM (GDPR-01). The hub receives
    #: participant data and eye-tracking telemetry, so on anything but loopback
    #: it refuses to start without them -- see
    #: :func:`src.central_server.server.resolve_tls`.
    #: ``tools/generate_hub_certificate.py`` creates a pair for a LAN hub.
    tls_certfile: Path | None = None
    tls_keyfile: Path | None = None

    #: Start on plain HTTP on a non-loopback interface anyway. For a disposable
    #: test setup only; every start logs that the hub is running insecurely.
    allow_insecure_http: bool = False

    @model_validator(mode="after")
    def _tls_pair(self) -> HubSettings:
        """A certificate without its key (or the reverse) is a typo, not a choice."""
        if (self.tls_certfile is None) != (self.tls_keyfile is None):
            raise ValueError("hub.tls_certfile and hub.tls_keyfile must be set together")
        return self


class AcquisitionSettings(BaseSettings):
    """The telemetry capture loop."""

    default_max_sampling_hz: float = Field(default=120.0, gt=0, le=1000)

    #: Refresh-rate headroom for jitter, applied when the HMD reports its rate.
    sampling_headroom: float = Field(default=1.2, ge=1.0, le=2.0)

    #: Quest standalone UDP stream. Binds all interfaces because the headset is
    #: a separate device on the LAN.
    udp_host: str = "0.0.0.0"  # noqa: S104 - the headset is a remote device
    udp_port: int = Field(default=5005, ge=1, le=65535)


class SyncSettings(BaseSettings):
    """Background upload and heartbeat loops."""

    interval_sec: float = Field(default=20.0, gt=0)
    heartbeat_interval_sec: float = Field(default=30.0, gt=0)

    #: Downsample cap for telemetry sent to the browser. Above roughly this,
    #: the React charts stop being interactive.
    max_frames_to_client: int = Field(default=60_000, gt=0)


class Settings(BaseSettings):
    """Root configuration object. Get it from :func:`get_settings`."""

    model_config = SettingsConfigDict(
        env_prefix="VRT_",
        env_nested_delimiter="__",
        extra="forbid",
        validate_default=True,
    )

    paths: PathSettings = Field(default_factory=PathSettings)
    central: CentralServerSettings = Field(default_factory=CentralServerSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    hub: HubSettings = Field(default_factory=HubSettings)
    acquisition: AcquisitionSettings = Field(default_factory=AcquisitionSettings)
    sync: SyncSettings = Field(default_factory=SyncSettings)

    @model_validator(mode="after")
    def _no_port_collision(self) -> Settings:
        """The workstation API and the hub must not fight over a port.

        They can legitimately run on one machine during development, and the
        symptom of a collision -- one of them silently failing to bind -- is
        tedious to diagnose.
        """
        if self.api.host == self.hub.host and self.api.port == self.hub.port:
            raise ValueError(
                f"api and hub are both configured on {self.api.host}:{self.api.port}; "
                "set VRT_API__PORT or VRT_HUB__PORT"
            )
        return self

    def require_central_url(self) -> str:
        """Return the hub URL, or explain that it has not been configured.

        Raises:
            RuntimeError: naming the two ways to set it. Callers that can carry
                on without the hub should read ``central.url`` and check for
                None instead of calling this.
        """
        if not self.central.url:
            raise RuntimeError(
                "No central server URL configured. Set it in the app under "
                "Settings, or with VRT_CENTRAL__URL=http://<host>:9000"
            )
        return self.central.url

    def ensure_directories(self) -> None:
        """Create the data directories this installation writes to.

        Called explicitly at startup rather than as a side effect of building
        Settings, so that merely reading configuration never touches the disk.
        """
        for directory in (
            self.paths.sessions_dir,
            self.paths.session_logs_dir,
            self.paths.logs_dir,
            self.paths.appdata_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def _load_config_file(data_root: Path) -> dict[str, Any]:
    """Read ``config.toml`` from the data root, if it is there.

    A malformed file raises rather than being ignored: silently falling back to
    defaults because of a typo is how an install ends up writing to the wrong
    directory without anyone noticing.
    """
    config_path = data_root / "config.toml"
    if not config_path.is_file():
        return {}
    try:
        with config_path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{config_path} is not valid TOML: {exc}") from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the resolved settings for this process.

    Cached: configuration is read once and does not change under a running
    process. Tests that need a different root call :func:`reset_settings_cache`.
    """
    file_values = _load_config_file(Path.cwd())
    return Settings(**file_values)


def reset_settings_cache() -> None:
    """Drop the cached Settings so the next call re-reads the environment.

    For tests and for the desktop app after the researcher changes the data
    root. Not a general-purpose reconfiguration hook: objects already holding a
    resolved path keep it.
    """
    get_settings.cache_clear()
