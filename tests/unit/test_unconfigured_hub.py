# tests/unit/test_unconfigured_hub.py
"""A workstation with no hub address configured never makes the request.

The bug these tests pin was visible in a normal dev run, and read as a network
problem::

    Patient sync failed, queued for retry: Invalid URL '/data/upload-patient':
    No scheme supplied. Perhaps you meant https:///data/upload-patient?

Nothing was wrong with the network. ``CentralServerSettings.url`` has no
default -- deliberately, so that an unconfigured install says it is
unconfigured rather than failing against the old ``192.168.1.X`` placeholder --
so ``Container.central_url()`` returned ``""``, and every client built its URL
with an f-string::

    f"{self.central_server_url}/data/upload-patient"   # -> "/data/upload-patient"

``requests`` rejects that with ``MissingSchema``, which subclasses
``RequestException``, which is exactly what each client catches as "the hub is
unreachable". So the docstrings' promise -- *"Empty when the hub is
unconfigured. That is a supported state: uploads queue locally rather than
being attempted against a placeholder"* -- was documented and not implemented,
and the researcher was told to check their LAN.

Each test below asserts two things, and the first matters more than the second:
**no HTTP call was attempted**, and the work is still queued. A test that only
checked the returned reason would pass against a client that made the doomed
request and then relabelled the exception.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.storage.heartbeat_client import HeartbeatSender
from src.storage.hub_address import HUB_NOT_CONFIGURED, is_configured
from src.storage.patient_sync_client import PatientSyncClient
from src.storage.session_uploader import SessionUploader


class _RecordingHttp:
    """An HTTP client that records calls and fails them the way an offline LAN does.

    It records *before* raising, so a client that attempts a request against an
    empty address is caught by the call log rather than by the reason string it
    happens to return afterwards.
    """

    def __init__(self) -> None:
        import requests

        self.RequestException = requests.RequestException
        self.calls: list[tuple[str, str]] = []

    def _fail(self, method: str, url: str) -> Any:
        self.calls.append((method, url))
        raise self.RequestException(f"stubbed: unreachable ({method} {url})")

    def get(self, url: str, *_: Any, **__: Any) -> Any:
        return self._fail("GET", url)

    def post(self, url: str, *_: Any, **__: Any) -> Any:
        return self._fail("POST", url)

    def put(self, url: str, *_: Any, **__: Any) -> Any:
        return self._fail("PUT", url)

    def delete(self, url: str, *_: Any, **__: Any) -> Any:
        return self._fail("DELETE", url)


@pytest.fixture
def cache(tmp_path: Path):
    """A licence cache on a throwaway database, activated.

    Activated because every client checks the licence first: an inactive one
    would short-circuit before reaching the address check and the test would
    pass for the wrong reason.
    """
    from src.license_service.local_cache import LocalLicenseCache

    cache = LocalLicenseCache(tmp_path / "license_cache.db")
    cache.save(
        activation_id="act-1",
        license_key="KEY-0001",
        hardware_fingerprint="fp",
        license_id="lic-1",
        machine_label="lab-workstation-1",
        server_expires_at=None,
    )
    return cache


@pytest.fixture
def http() -> _RecordingHttp:
    return _RecordingHttp()


# ─────────────────────────────────────────────────────────────────────────────
# The predicate
# ─────────────────────────────────────────────────────────────────────────────


def test_only_an_absent_address_counts_as_unconfigured() -> None:
    """A set-but-wrong address is a network error, and must stay one.

    The temptation when fixing this is to validate the URL here and report
    anything unparsable as "not configured". That would be a worse lie than the
    one being fixed: the researcher *did* configure it, and what they need to
    know is that it did not answer.
    """
    assert is_configured("http://10.0.0.9:9000")
    assert is_configured("hub.invalid")  # wrong, but set -- let the request fail
    assert not is_configured("")
    assert not is_configured("   ")
    assert not is_configured(None)


# ─────────────────────────────────────────────────────────────────────────────
# Patients — the path the reported log line came from
# ─────────────────────────────────────────────────────────────────────────────


def test_a_patient_edit_with_no_hub_is_queued_without_a_request(cache, http) -> None:
    client = PatientSyncClient("", cache, http=http)

    result = client.sync_patient({"patient_id": "p-1", "display_name": "A"})

    assert http.calls == [], f"a request was attempted against an empty address: {http.calls}"
    assert result == {"ok": False, "reason": HUB_NOT_CONFIGURED}
    queued = cache.list_pending_patient_syncs()
    assert [item["patient_id"] for item in queued] == ["p-1"]


def test_the_queued_patient_is_not_charged_a_failed_attempt(cache, http) -> None:
    """So it goes out on the first sweep after a hub is configured.

    ``is_ready_for_retry`` spaces retries by attempt count. Recording this as a
    failure would push the item into a backoff window earned by a request that
    was never sent -- so a researcher who fills in the address would watch
    nothing happen for up to five minutes and reasonably conclude it had not
    worked.
    """
    client = PatientSyncClient("", cache, http=http)

    client.sync_patient({"patient_id": "p-1", "display_name": "A"})

    assert (cache.list_pending_patient_syncs()[0]["attempts"] or 0) == 0


def test_a_patient_sync_resumes_once_an_address_is_set(cache, http) -> None:
    """The address is late-bound, so configuring one needs no restart.

    Pairs with the test above: together they say the queued item is both still
    there and immediately eligible.
    """
    client = PatientSyncClient(
        lambda: cache.get_config("central_server_url", "") or "", cache, http=http
    )
    client.sync_patient({"patient_id": "p-1", "display_name": "A"})
    assert http.calls == []

    cache.set_config("central_server_url", "http://10.0.0.9:9000")
    client.retry_pending()

    assert http.calls == [("POST", "http://10.0.0.9:9000/data/upload-patient")]


# ─────────────────────────────────────────────────────────────────────────────
# Sessions
# ─────────────────────────────────────────────────────────────────────────────


def test_a_finished_session_with_no_hub_is_queued_without_a_request(
    cache, http, tmp_path: Path
) -> None:
    """The costliest case: this runs at the end of a recording.

    The file exists and is the researcher's only copy, so "queued" is the part
    that must not regress.
    """
    parquet = tmp_path / "session.parquet"
    parquet.write_bytes(b"not really parquet")
    uploader = SessionUploader("", cache, http=http)

    result = uploader.upload(parquet, "s-1", {"subject": "A"})

    assert http.calls == []
    assert result == {"ok": False, "reason": HUB_NOT_CONFIGURED}
    assert [item["session_id"] for item in cache.list_pending_uploads()] == ["s-1"]


def test_a_session_log_with_no_hub_is_queued_without_a_request(cache, http, tmp_path: Path) -> None:
    log = tmp_path / "session_s-1.log"
    log.write_text("hello")
    uploader = SessionUploader("", cache, http=http)

    result = uploader.upload_log(log, "s-1")

    assert http.calls == []
    assert result == {"ok": False, "reason": HUB_NOT_CONFIGURED}
    assert [item["session_id"] for item in cache.list_pending_session_logs()] == ["s-1"]


def test_a_metadata_resync_with_no_hub_is_skipped_and_queues_nothing(cache, http) -> None:
    """This one deliberately does not queue -- the local row is the truth.

    Asserted explicitly so a later change that "helpfully" adds it to a retry
    queue has to argue with a test rather than slip through.
    """
    uploader = SessionUploader("", cache, http=http)

    result = uploader.update_remote_metadata("s-1", {"notes": "x"})

    assert http.calls == []
    assert result == {"ok": False, "reason": HUB_NOT_CONFIGURED}
    assert cache.list_pending_uploads() == []


# ─────────────────────────────────────────────────────────────────────────────
# Heartbeat
# ─────────────────────────────────────────────────────────────────────────────


def test_the_heartbeat_does_not_ping_an_unconfigured_hub(cache, http) -> None:
    """Otherwise: one doomed request every 30 seconds for the life of the process.

    Nothing was lost when it failed -- a heartbeat is not queued -- but it is
    the loop that would have kept the mistake permanently in the log.
    """
    sender = HeartbeatSender(
        central_server_url_provider=lambda: "",
        local_license_cache=cache,
        http=http,
    )

    assert sender.send_once() is False
    assert http.calls == []


def test_the_heartbeat_still_pings_a_configured_hub(cache, http) -> None:
    """The guard must not be reachable when an address exists.

    Without this, a guard with an inverted condition passes every test above.
    """
    sender = HeartbeatSender(
        central_server_url_provider=lambda: "http://10.0.0.9:9000/",
        local_license_cache=cache,
        http=http,
    )

    assert sender.send_once() is False  # the stub raises; the call is the point
    assert http.calls == [("POST", "http://10.0.0.9:9000/client/heartbeat")]
