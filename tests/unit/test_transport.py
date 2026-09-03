# tests/unit/test_transport.py
"""The HTTP port and its one production implementation (VRT-14).

Small file, and the reason it exists is narrow: ``default_http_client()``
returns the ``requests`` module through a ``cast``, and a cast is a promise the
type checker takes on faith. These tests are where the promise is checked.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.application.ports import HttpClient
from src.infrastructure.transport import default_http_client


def test_the_real_client_satisfies_the_port():
    """The cast in `default_http_client` is not a lie.

    If `requests` ever loses one of the four verbs, or moves
    `RequestException`, this fails here rather than at the first upload on a
    researcher's machine.
    """
    client = default_http_client()

    assert isinstance(client, HttpClient)
    for verb in ("get", "post", "put", "delete"):
        assert callable(getattr(client, verb))
    assert issubclass(client.RequestException, Exception)


def test_importing_the_transport_module_does_not_import_requests():
    """`requests` is imported inside the function, and that is load-bearing.

    ``tests/unit/test_no_import_time_io.py`` asserts that importing any module
    under ``src/`` performs no I/O. ``requests`` initialises its adapters and
    TLS stack on import, so hoisting that import to module scope would put it
    back into every import of the application.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import src.infrastructure.transport; print('requests' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False", (
        "importing src.infrastructure.transport pulled in requests; "
        "the import belongs inside default_http_client()"
    )


def test_a_stub_missing_the_exception_type_is_not_a_client():
    """The attribute every caller catches on is part of the contract.

    A fake with the four verbs and no ``RequestException`` produces a suite
    where the offline branch is never reached -- the exact shape of the
    false-green fixture VRT-12 removed.
    """

    class _VerbsOnly:
        def get(self, url: str, **kwargs: Any) -> Any: ...
        def post(self, url: str, **kwargs: Any) -> Any: ...
        def put(self, url: str, **kwargs: Any) -> Any: ...
        def delete(self, url: str, **kwargs: Any) -> Any: ...

    assert not isinstance(_VerbsOnly(), HttpClient)


@pytest.mark.parametrize("missing", ["get", "post", "put", "delete"])
def test_a_stub_missing_a_verb_is_not_a_client(missing: str):
    """All four verbs are used by some router, so all four are required."""
    import requests

    namespace: dict[str, Any] = {"RequestException": requests.RequestException}
    for verb in ("get", "post", "put", "delete"):
        if verb != missing:
            namespace[verb] = lambda *_args, **_kwargs: None

    stub_type = type("_PartialClient", (), namespace)
    assert not isinstance(stub_type(), HttpClient)
