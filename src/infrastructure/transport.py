# src/infrastructure/transport.py
"""The one place the real HTTP library is named (VRT-14).

``requests`` used to be imported at module scope in four files:
``session_uploader``, ``patient_sync_client``, ``heartbeat_client`` and the
container. VRT-12 put every *router's* outbound call behind
``container.http``, which is why the routers are testable offline -- but the
three clients kept their own reference, so the characterisation suite had to
reach in and replace two bound methods to stay off the network, with a comment
saying VRT-14 would fix it. This is that fix.

Naming the library in exactly one module is what makes the injection real
rather than decorative. A client that can fall back to a module-level
``requests`` when nothing is passed will do so the first time someone forgets,
and the test that was supposed to be offline goes to the network instead --
silently, because an unreachable server and a stub that raises look identical
from the assertion's side.

GDPR-01 made it the one place the *transport rule* lives as well: nothing is
sent to the hub over plain ``http://`` except on loopback, and a hub whose
certificate comes from its own small CA is trusted through
``central.ca_bundle``. See :class:`PolicyEnforcingHttpClient`.
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

from src.application.ports import HttpClient

if TYPE_CHECKING:
    from src.config.settings import CentralServerSettings

logger = logging.getLogger(__name__)

#: Returned in the refusal message, so the UI and the logs can recognise it.
INSECURE_TRANSPORT = "insecure_transport_refused"

#: Returned in place of it when there is no hub address to judge at all.
NO_HUB_ADDRESS = "no_hub_address"


def is_loopback_host(host: str | None) -> bool:
    """Whether ``host`` names this machine: ``localhost`` or a loopback address."""
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def insecure_transport_reason(url: str, *, allow_insecure_http: bool = False) -> str | None:
    """Why ``url`` may not carry participant data, or None if it may (GDPR-01).

    ``https://`` is always acceptable. ``http://`` is acceptable to loopback
    only -- a hub on the same machine, which is how the test suite and a
    one-box development setup run -- unless the operator has set the explicit
    development flag. Anything else is refused.

    Args:
        url: The full request URL.
        allow_insecure_http: ``central.allow_insecure_http``.

    Returns:
        A sentence for the log and the UI, or None.
    """
    parts = urlsplit(url)
    if not parts.scheme and not parts.netloc:
        # Callers build "<hub>/auth/login" from the configured address, so an
        # unset one arrives here as a bare path. Refused all the same -- but
        # "refusing to send data to :// without TLS" sent people after
        # certificates when the workstation simply had no hub address.
        return (
            f"{NO_HUB_ADDRESS}: no hub address is set on this workstation. Copy "
            "hub-ca.pem and config.toml from the hub's workstation kit into "
            "%APPDATA%\\VRTelemetry\\data and restart the app, or enter the hub's "
            "https:// address under Central Server Address."
        )
    if parts.scheme == "https":
        return None
    if parts.scheme == "http" and (allow_insecure_http or is_loopback_host(parts.hostname)):
        return None
    return (
        f"{INSECURE_TRANSPORT}: refusing to send data to {parts.scheme}://{parts.netloc} "
        f"without TLS. Use an https:// hub address (see tools/generate_hub_certificate.py), "
        f"or set central.allow_insecure_http = true on a disposable test setup only."
    )


@dataclass(frozen=True)
class TlsPolicy:
    """The transport rules every outbound request is held to (GDPR-01)."""

    allow_insecure_http: bool = False
    ca_bundle: Path | None = None


class PolicyEnforcingHttpClient:
    """An :class:`HttpClient` that refuses plain HTTP and trusts the hub's CA.

    Wraps the real client rather than living in each caller, for the reason
    the rest of this module exists: the four places that talk to the hub
    (session and patient uploads, the heartbeat, and the routers' own calls)
    would each have to remember the rule, and the first one that forgot would
    send eye-tracking data across the LAN in clear text without any test
    noticing. Here it is one object, and nothing reaches the network around it.

    A refusal is raised as the inner client's ``RequestException``, so every
    caller's existing "hub unreachable" handling applies: the work is queued
    locally, nothing is lost, and the log says exactly why.
    """

    def __init__(self, inner: HttpClient, policy: TlsPolicy) -> None:
        self._inner = inner
        self._policy = policy
        #: Re-exported: callers catch ``http.RequestException``.
        self.RequestException: type[Exception] = inner.RequestException

    def _prepare(self, url: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        reason = insecure_transport_reason(
            url, allow_insecure_http=self._policy.allow_insecure_http
        )
        if reason is not None:
            logger.error(reason)
            raise self.RequestException(reason)
        if url.startswith("http://") and not is_loopback_host(urlsplit(url).hostname):
            logger.warning(
                f"central.allow_insecure_http is set: sending to {url} WITHOUT TLS. "
                f"Never use this setting with real participant data."
            )
        if url.startswith("https://") and self._policy.ca_bundle and "verify" not in kwargs:
            kwargs["verify"] = str(self._policy.ca_bundle)
        return kwargs

    def get(self, url: str, **kwargs: Any) -> Any:
        return self._inner.get(url, **self._prepare(url, kwargs))

    def post(self, url: str, **kwargs: Any) -> Any:
        return self._inner.post(url, **self._prepare(url, kwargs))

    def put(self, url: str, **kwargs: Any) -> Any:
        return self._inner.put(url, **self._prepare(url, kwargs))

    def delete(self, url: str, **kwargs: Any) -> Any:
        return self._inner.delete(url, **self._prepare(url, kwargs))


def default_http_client(central: CentralServerSettings | None = None) -> HttpClient:
    """The production HTTP client: ``requests``, held to the TLS policy.

    Imported inside the function rather than at module scope: importing this
    module must stay free of side effects, and ``requests`` initialises its
    adapters and TLS stack on import (see
    ``tests/unit/test_no_import_time_io.py``).

    Args:
        central: The workstation's hub settings, for ``allow_insecure_http``
            and ``ca_bundle``. Defaults to the process settings.

    Returns:
        ``requests`` wrapped in :class:`PolicyEnforcingHttpClient`. The cast is
        the one place ``requests`` is asserted to satisfy :class:`HttpClient`;
        ``tests/unit/test_transport.py`` checks it holds.
    """
    import requests

    if central is None:
        from src.config import get_settings

        central = get_settings().central

    policy = TlsPolicy(
        allow_insecure_http=central.allow_insecure_http,
        ca_bundle=central.ca_bundle,
    )
    return PolicyEnforcingHttpClient(cast(HttpClient, requests), policy)
