# src/storage/hub_address.py
"""Whether there is a hub to talk to at all.

``CentralServerSettings.url`` has no default on purpose, and
``Container.central_url()`` returns ``""`` when neither the researcher's saved
setting nor configuration supplies one. Every docstring around that value
already promised what should happen next: *"Empty when the hub is unconfigured.
That is a supported state: uploads queue locally rather than being attempted
against a placeholder."*

Nothing implemented it. ``f"{self.central_server_url}/data/upload-patient"``
with an empty address is the string ``"/data/upload-patient"``, which
``requests`` rejects with ``MissingSchema`` -- a subclass of
``RequestException``, so it landed in the same ``except`` clause as an
unreachable LAN and was logged as one::

    Patient sync failed, queued for retry: Invalid URL '/data/upload-patient':
    No scheme supplied. Perhaps you meant https:///data/upload-patient?

Two things were wrong with that. The researcher was told to check their network
when the actual problem was a setting they had never filled in; and the item was
queued behind a retry backoff that could never succeed, so every sweep spent a
round trip re-discovering the same missing configuration.

This module is the one place that answers "is an address set?", so the three
clients that talk to the hub answer it the same way and the reason string they
return is the same string the UI can switch on.
"""

from __future__ import annotations

#: Returned in place of ``network_error`` when no hub address is set. Distinct
#: on purpose: the two states look identical in a log and need opposite
#: responses from the researcher -- check the cable, versus fill in the setting.
HUB_NOT_CONFIGURED = "hub_not_configured"

#: What to tell the researcher. Says what to do, because "no central server
#: configured" alone leaves them looking for a config file.
HUB_NOT_CONFIGURED_MESSAGE = (
    "no central server address is configured on this machine "
    "(set one under Settings -> Central server, or `central.url` in config.toml)"
)


def is_configured(url: str | None) -> bool:
    """Whether ``url`` is an address a request can actually be sent to.

    Deliberately not a URL validator. The one failure this guards against is
    the empty string, because that is the value the application itself produces
    for an unconfigured install and the only one it produces routinely. An
    address that is set but wrong stays a network error, which is what it is:
    the researcher typed something, and the honest report is that it did not
    answer.
    """
    return bool((url or "").strip())
