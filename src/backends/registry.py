# src/backends/registry.py
"""Which VR backend to use, decided in one place (VRT-14).

Selection used to be four lines inside ``TelemetryEngine.start()``::

    if backend_mode == "openxr":
        self.backend = OpenXRBackend()
    elif backend_mode == "oculus":
        self.backend = OculusBackend()
    else:  # "auto" vagy "steamvr" esetén
        self.backend = SteamVROverlayBackend()

Three things were wrong with it, and none of them is the style.

**It made every backend a hard import.** Those three classes were imported at
``src/core/engine.py``'s module scope, so importing the engine imported all of
them, and therefore ``xr`` and ``openvr``. ``pyproject.toml`` says as much in
the ``workstation`` extra: openvr "is required today to import ANY module under
src.core -- including from the unit tests". A registry that imports the chosen
backend and only the chosen one removes that. The engine now imports on a
machine with no VR bindings at all, which is what
``tests/unit/test_backend_registry.py`` asserts.

**An unrecognised name recorded anyway.** The ``else`` swallowed every
misspelling. ``--backend openxrr`` did not fail; it started a SteamVR session,
and the researcher found out when they opened the data. Unknown names now raise
:class:`BackendUnavailableError` naming what is available.

**A missing binding was an ImportError from the wrong place.** Selecting the
Oculus backend on a host without ``pyovr`` failed at import of the *engine*, in
a traceback that named neither the backend nor the choice that required it.

What this module deliberately does not change
---------------------------------------------

``"auto"`` still resolves to SteamVR, exactly as the ``else`` branch did. It is
tempting to make it try each backend's ``initialize()`` in priority order, and
that is probably right -- but it is a behaviour change on the one path that
cannot be executed without a headset, so it belongs in a ticket that can be
verified on hardware rather than smuggled into a refactor. :data:`AUTO_TARGET`
is where that decision lives when someone makes it.

``"quest_udp"`` is not registered here. It is not an :class:`IVRBackend` at all:
the Quest streams frames over a socket into the synchroniser, so the engine runs
a different loop rather than polling a backend. Modelling both as one port is
the ``FrameSource`` work in the rest of VRT-14.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module

from src.core.exceptions import BackendUnavailableError
from src.core.interfaces import IVRBackend


@dataclass(frozen=True)
class BackendEntry:
    """One selectable acquisition backend.

    Attributes:
        name: The value a caller passes as ``--backend`` or in the API's
            ``backend`` field. Stable; it appears in saved session metadata.
        module: Dotted path, imported on selection rather than at import time.
        attribute: The :class:`IVRBackend` implementation inside that module.
        summary: One line, shown when a selection fails so the message can say
            what the alternatives actually are.
        requires: Third-party distributions the backend needs. Named for the
            error message only -- availability is decided by trying the import,
            never by guessing from this tuple.
        availability_flag: Name of a module-level boolean that must be true for
            the backend to be usable. Only ``backend_ocolus`` needs one: it
            guards ``import ovr`` in a try/except and sets ``OVR_AVAILABLE``, so
            its module imports cleanly on a host with no LibOVR at all and
            "the module imported" would otherwise be reported as "the backend
            is available". The other three import their bindings unguarded, so
            for them the import *is* the check.
    """

    name: str
    module: str
    attribute: str
    summary: str
    requires: tuple[str, ...] = ()
    availability_flag: str | None = None


#: What ``"auto"`` means today. Preserved from the branch this module replaces;
#: see the note above before changing it.
AUTO_TARGET = "steamvr"

_REGISTRY: dict[str, BackendEntry] = {
    "steamvr": BackendEntry(
        name="steamvr",
        module="src.backends.backend_steamvr",
        attribute="SteamVROverlayBackend",
        summary="SteamVR/OpenVR overlay — Valve Index, Vive Pro Eye, Bigscreen Beyond",
        requires=("openvr",),
    ),
    "openxr": BackendEntry(
        name="openxr",
        module="src.backends.backend_openxr",
        attribute="OpenXRBackend",
        summary="OpenXR, using XR_MND_headless where the runtime offers it",
        requires=("pyopenxr",),
    ),
    "openxr_headless": BackendEntry(
        name="openxr_headless",
        module="src.backends.openxr_headless",
        attribute="OpenXRHeadlessBackend",
        summary=(
            "OpenXR with a dummy D3D11 binding, for Windows runtimes that "
            "refuse a session without graphics"
        ),
        requires=("pyopenxr",),
    ),
    "oculus": BackendEntry(
        name="oculus",
        module="src.backends.backend_ocolus",
        attribute="OculusBackend",
        summary="Native LibOVR",
        requires=("pyovr",),
        availability_flag="OVR_AVAILABLE",
    ),
}


def known_backends() -> tuple[str, ...]:
    """Every registered name, sorted. Does not import anything."""
    return tuple(sorted(_REGISTRY))


def register(entry: BackendEntry) -> None:
    """Add or replace a backend.

    Exists so an out-of-tree backend, or a test's fake, can be selected by name
    through the same path production uses -- rather than by patching a module
    attribute, which is the pattern this project has already been bitten by
    (see the note in tests/characterisation/conftest.py).

    Args:
        entry: The backend to register. An existing name is replaced.
    """
    _REGISTRY[entry.name] = entry


def resolve(name: str) -> BackendEntry:
    """The entry for ``name``, resolving ``"auto"``.

    Args:
        name: A registered name, or ``"auto"``.

    Returns:
        The matching entry.

    Raises:
        BackendUnavailableError: if the name is not registered. The message
            lists what is, because the failure this replaces was a typo that
            silently recorded a session on the wrong device.
    """
    wanted = AUTO_TARGET if name == "auto" else name
    entry = _REGISTRY.get(wanted)
    if entry is None:
        options = ", ".join(known_backends())
        raise BackendUnavailableError(
            f"Unknown acquisition backend {name!r}. Available: {options} (or 'auto', "
            f"which selects {AUTO_TARGET!r})."
        )
    return entry


def create_backend(name: str) -> IVRBackend:
    """Import and construct the backend called ``name``.

    The import happens here and nowhere else, which is what keeps the engine
    importable on a machine with no VR runtime bindings.

    Args:
        name: A registered name, or ``"auto"``.

    Returns:
        A constructed backend. Nothing is initialised: binding to the runtime
        is ``initialize()``'s job, and it happens on the acquisition thread.

    Raises:
        BackendUnavailableError: if the name is unknown, or if its bindings are
            not installed. Both are the same thing to the caller -- this
            workstation cannot record with that backend -- and both now say
            which package is missing instead of surfacing as an ImportError
            from a module the caller never mentioned.
    """
    entry = resolve(name)
    try:
        module = import_module(entry.module)
    except ImportError as exc:
        needed = " and ".join(entry.requires) or "its runtime bindings"
        raise BackendUnavailableError(
            f"The {entry.name!r} backend ({entry.summary}) is not available on this "
            f"machine: {exc}. Install {needed}, or choose another backend "
            f"({', '.join(available_backends()) or 'none are available'})."
        ) from exc

    if entry.availability_flag and not getattr(module, entry.availability_flag, False):
        raise BackendUnavailableError(
            f"The {entry.name!r} backend ({entry.summary}) imported, but its runtime "
            f"bindings are absent ({entry.module}.{entry.availability_flag} is false). "
            f"Install {' and '.join(entry.requires)}, or choose another backend "
            f"({', '.join(available_backends()) or 'none are available'})."
        )

    backend_class: type[IVRBackend] = getattr(module, entry.attribute)
    return backend_class()


def available_backends() -> tuple[str, ...]:
    """The registered backends whose modules import on this machine.

    Decided by attempting the import, not by inspecting ``requires``: a package
    can be installed and still fail to load -- a missing runtime DLL is the
    common case on Windows -- and a list that claims otherwise is worse than no
    list. Where a module imports cleanly without its bindings, its
    ``availability_flag`` is consulted too; see :class:`BackendEntry`.

    "Available" here means "can be constructed", not "will bind to a runtime".
    Whether a headset is actually plugged in is only knowable by calling
    ``initialize()``, which starts a session, so it is not something a listing
    function may do.

    Importing a backend module is not free (``openvr`` and ``xr`` load native
    libraries), so this is for diagnostics and for the failure message above,
    not for the recording path.

    Returns:
        Names, sorted. Possibly empty, which is the honest answer on a machine
        with no VR bindings installed.
    """
    usable = []
    for name in known_backends():
        entry = _REGISTRY[name]
        try:
            module = import_module(entry.module)
        except ImportError:
            continue
        if entry.availability_flag and not getattr(module, entry.availability_flag, False):
            continue
        usable.append(name)
    return tuple(usable)
