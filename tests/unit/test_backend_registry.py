# tests/unit/test_backend_registry.py
"""Backend selection, and the import weight it used to carry (VRT-14).

The registry's headline claim is not "selection is tidier now". It is that
``src.core.engine`` no longer drags every VR binding into the process just to be
imported -- a claim worth a subprocess test, because it is exactly the kind of
property that regresses the moment someone adds a convenience import at the top
of a file.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from src.backends import registry
from src.core.exceptions import BackendUnavailableError


def _run(source: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - the argv is this file's own literal
        [sys.executable, "-c", textwrap.dedent(source)],
        capture_output=True,
        text=True,
    )


def test_importing_the_engine_does_not_import_any_vr_binding():
    """The property the registry exists for.

    ``pyproject.toml``'s ``workstation`` extra used to say openvr "is required
    today to import ANY module under src.core -- including from the unit
    tests", because ``engine.py`` imported all three backend classes at module
    scope. This blocks ``xr``, ``openvr`` and ``ovr`` at the import hook and
    asserts the engine still imports, which is the same thing a researcher's
    machine without a headset experiences.
    """
    result = _run(
        """
        import sys

        BLOCKED = {"xr", "openvr", "ovr"}

        class _Blocker:
            def find_module(self, name, path=None):
                return self if name.split(".")[0] in BLOCKED else None

            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] in BLOCKED:
                    raise ImportError(f"blocked for this test: {name}")
                return None

            def load_module(self, name):
                raise ImportError(f"blocked for this test: {name}")

        sys.meta_path.insert(0, _Blocker())

        import src.core.engine  # noqa: F401

        assert not BLOCKED & set(sys.modules), sorted(BLOCKED & set(sys.modules))
        print("OK")
        """
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_auto_still_means_what_the_else_branch_meant():
    """Preserved on purpose, and pinned so a change to it is deliberate.

    Making ``auto`` probe each backend in turn is probably right and is
    explicitly out of scope: it is a behaviour change on the one path that
    cannot run without a headset.
    """
    assert registry.AUTO_TARGET == "steamvr"
    assert registry.resolve("auto").name == "steamvr"


def test_an_unknown_backend_name_is_refused_rather_than_substituted():
    """The defect this replaces.

    ``--backend openxrr`` used to fall through the ``else`` and record a
    SteamVR session. Nothing said so at the time, and the only evidence
    afterwards was in the data.
    """
    with pytest.raises(BackendUnavailableError) as caught:
        registry.resolve("openxrr")

    message = str(caught.value)
    assert "openxrr" in message
    for name in registry.known_backends():
        assert name in message, "the error must list what is actually selectable"


def test_a_backend_whose_bindings_are_absent_names_the_package():
    """An ImportError from a module the caller never mentioned is not an answer.

    ``backend_ocolus`` guards ``import ovr`` and sets ``OVR_AVAILABLE``, so its
    module imports on any host -- which is why the entry carries an
    availability flag. Without it the registry would report the Oculus backend
    as available on every machine and fail at ``initialize()`` instead.
    """
    if "oculus" in registry.available_backends():
        pytest.skip("pyovr is installed on this machine, so there is no absence to test")

    with pytest.raises(BackendUnavailableError) as caught:
        registry.create_backend("oculus")

    assert "pyovr" in str(caught.value)


def test_available_backends_never_claims_more_than_it_can_construct():
    """Whatever it lists must actually construct, on this machine, right now."""
    for name in registry.available_backends():
        backend = registry.create_backend(name)
        assert hasattr(backend, "initialize")
        assert hasattr(backend, "poll_frame")
        assert hasattr(backend, "shutdown")


def test_a_backend_can_be_registered_by_name_rather_than_patched():
    """The seam that replaces `monkeypatch.setattr` on the engine's namespace.

    Selection is reached through the same function production uses, so a test
    that exercises it is exercising the real path rather than a lookalike.
    """
    constructed: list[str] = []

    class _Fake:
        def __init__(self) -> None:
            constructed.append("built")

        def initialize(self) -> bool:
            return True

        def poll_frame(self, _frame_index):  # pragma: no cover - not called here
            raise AssertionError

        def shutdown(self) -> None:
            pass

    import types

    module = types.ModuleType("tests_fake_backend_module")
    module.FakeBackend = _Fake
    sys.modules["tests_fake_backend_module"] = module
    try:
        registry.register(
            registry.BackendEntry(
                name="fake",
                module="tests_fake_backend_module",
                attribute="FakeBackend",
                summary="a fake, for tests",
            )
        )
        assert "fake" in registry.known_backends()
        assert isinstance(registry.create_backend("fake"), _Fake)
        assert constructed == ["built"]
    finally:
        registry._REGISTRY.pop("fake", None)
        sys.modules.pop("tests_fake_backend_module", None)


def test_the_cli_offers_exactly_what_the_registry_knows():
    """One list, not two.

    The `--backend` choices used to be hand-written beside the registry's
    contents, which is a pair that drifts: a backend added to one is invisible
    from the other until someone notices.
    """
    from src.interfaces.cli.record import build_parser

    choices = next(a.choices for a in build_parser()._actions if a.dest == "backend")

    assert list(choices) == ["auto", *registry.known_backends(), "quest_udp"]
