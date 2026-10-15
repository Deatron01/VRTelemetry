# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the desktop app's backend process (VRT-2).

``package.json`` has run ``pyinstaller build/backend.spec`` since the desktop
shell existed, and ``electron-builder`` copies ``build/dist-backend/
vrtelemetry-backend`` into the packaged app as ``resources/backend``. This file
was never written. ``git log --all -- build/backend.spec`` returns nothing: the
blanket ``build/`` ignore rule was removed and ``tools/check_repo_hygiene.py``
was taught to require the file, but the spec itself never existed, so
``npm run package`` has never been able to build on any clone.

Reconstructed from three sources rather than invented:

* ``VR_Telemetry.spec`` at ``126448c`` (deleted at ``3bedf8d``) -- the original,
  which froze the long-gone root ``main.py`` and named its output
  ``VR_Telemetry``;
* ``package.json`` -- fixes the spec's path, the dist layout and the collected
  directory name;
* ``electron/backend-manager.js:14`` -- spawns ``vrtelemetry-backend[.exe]``
  from ``resources/backend``, which fixes the executable name exactly.

Three deliberate differences from the original
----------------------------------------------

**The entry point is the server, not the recorder.** The original froze the
module that becomes ``vrtelemetry-record``: a CLI that exits immediately without
``--gdpr-consent`` and never binds a port. Electron waits for an HTTP server on
127.0.0.1:8000, so the packaged app could never have started even if the spec
had been present. ``src/server_entrypoint.py`` is what serves.

**The dynamic imports are declared.** ``EyeTrackingFactory._DRIVER_MODULES``
reaches the three eye-tracking drivers only through
``importlib.import_module``, and ``uvicorn`` selects its loop and protocol
implementations by name at startup. Neither is visible to an import-graph walk.

An honest note about the eye-tracking three, because it was checked rather than
assumed: **omitting them from this list changes nothing today.** A build without
them was made and its PYZ table of contents still contains all three. They
arrive through the ``if TYPE_CHECKING:`` block in ``src/eye_tracking/__init__``
-- the guard is false at runtime, but the import bytecode is still in the code
object, and PyInstaller reads bytecode.

They stay declared anyway, and the reason is the fragility of that route rather
than superstition. That block exists to type an unused PEP 562 facade whose own
docstring says nothing in this repository imports through it; VRT-14 or VRT-15
may reasonably delete it. If it goes, the drivers leave the bundle silently, and
the symptom is a packaged app that reports "no compatible biometric tracking
hardware found" on a headset that has it -- indistinguishable from an
unsupported HMD, and not reproducible from source. Eye data is the point of this
study. The three lines are cheap; that failure is not.

The VR backends genuinely do not need declaring: ``src/core/engine.py`` imports
all four at module scope, so the analyser follows them.

**UPX is off.** The original set ``upx=True``. UPX is usually not installed, so
the build emits warnings and silently produces an uncompressed binary anyway --
and where it *is* installed, compressed executables are a routine false positive
for Windows Defender, which for a lab install means the backend vanishing
between one machine and the next. A larger, boring binary is the better trade.

Build:  ``npm run build:backend``
Output: ``build/dist-backend/vrtelemetry-backend/vrtelemetry-backend[.exe]``
"""

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

# SPECPATH is injected by PyInstaller and is this file's directory (build/), so
# the project root is its parent. Derived rather than assumed from the working
# directory: `npm run build:backend` happens to run from the root, but a spec
# that only works from one cwd is a spec that breaks in CI.
PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))  # noqa: F821

datas: list = []
binaries: list = []
hiddenimports: list = []

# Both VR bindings ship loader libraries and JSON manifests beside their Python
# modules, which an import-graph walk does not see. collect_all is what the
# original spec used for openvr; pyopenxr needs the same treatment and never
# got it.
for _package in ("openvr", "xr"):
    _datas, _binaries, _hidden = collect_all(_package)
    datas += _datas
    binaries += _binaries
    hiddenimports += _hidden

# Package metadata, so src/version.py reports the installed version instead of
# its hand-kept fallback -- the frozen hub reported "1.0.0" on a 1.1.0 build
# before this. Needs the project installed in the build environment
# (`pip install -e .`), which both the release workflow and the README's
# contributor setup do; copy_metadata fails the build loudly otherwise, which
# is the right outcome for a bundle that would misreport itself.
datas += copy_metadata("vrtelemetry")

# Imported by name at runtime -- see the module docstring.
hiddenimports += [
    "src.eye_tracking.ext_eye_gaze",
    "src.eye_tracking.fb_social",
    "src.eye_tracking.htc_tracker",
    # FastAPI imports this only when a route declares Form()/File(), which the
    # auth, licence and upload routes do.
    "multipart",
    # tomllib is stdlib from 3.11; on the 3.10 leg settings.py falls back to
    # tomli inside a try/except that the analyser resolves to whichever exists.
    # Naming it keeps a 3.10 build honest.
    "tomli",
]
hiddenimports += collect_submodules("uvicorn")

a = Analysis(  # noqa: F821
    [os.path.join(PROJECT_ROOT, "src", "server_entrypoint.py")],
    pathex=[PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # torch and whisper were excluded by the original spec and are not
    # dependencies of this project; the two GUI toolkits are pulled in by
    # matplotlib-adjacent packages and would add tens of megabytes to a process
    # that never draws anything.
    excludes=["torch", "whisper", "matplotlib", "tkinter", "PyQt5", "PySide6"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    # Must match electron/backend-manager.js:14 exactly.
    name="vrtelemetry-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # The Electron shell reads this process's stdout and stderr to know the
    # backend is alive, so it keeps a console stream.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    # Must match package.json's extraResources `from` path exactly.
    name="vrtelemetry-backend",
)
