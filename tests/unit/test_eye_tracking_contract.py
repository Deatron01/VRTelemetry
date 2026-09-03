# tests/unit/test_eye_tracking_contract.py
"""The session belongs to the backend, not to the eye-tracking driver (VRT-17).

`xrAttachSessionActionSets` may be called **at most once per session**. Two of
the three drivers knew that; `XR_EXT_eye_gaze_interaction` attached its own
action set inside `initialize()`, so the backend's own attach -- which runs
afterwards and carries the controller actions -- failed with
`XR_ERROR_ACTIONSETS_ALREADY_ATTACHED`. `initialize()` caught the XrException
and returned False, and the OpenXR backend could not bind at all.

Which headsets that hit is decided by `get_priority()`: Meta social eye tracking
is 100, HTC facial tracking is 50, the cross-vendor Khronos extension is 10. So
the driver that broke the backend was selected exactly when neither vendor
extension was present -- a Valve Index, a Varjo, a Pimax, anything exposing only
`XR_EXT_eye_gaze_interaction`. On those, recording was impossible, and after
VRT-13 it fails loudly with "could not bind to a VR runtime. Check that the
headset is connected" -- which is the one thing that was not wrong.

The tests below are deliberately static. Exercising the real failure needs a
headset and an OpenXR runtime; the *rule* it violates is a property of the
source, and a property of the source can be checked on every commit.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

DRIVER_DIR = Path(__file__).resolve().parents[2] / "src/eye_tracking"

#: Session-wide OpenXR calls. The backend owns the session and is the only
#: thing that knows the full set of actions, so it makes both of these calls
#: exactly once. A driver that makes either one either breaks the backend's
#: attach or deactivates the backend's action sets mid-frame.
BACKEND_ONLY_CALLS = frozenset({"attach_session_action_sets", "sync_actions"})

DRIVER_FILES = sorted(
    p for p in DRIVER_DIR.glob("*.py") if p.name not in {"__init__.py", "factory.py"}
)


def _xr_calls(path: Path) -> set[str]:
    """Every ``xr.<name>(...)`` called in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "xr"
    }


def test_the_driver_directory_was_actually_found() -> None:
    """Guards the tests below rather than the drivers.

    A glob that silently matches nothing passes every assertion that follows.
    """
    assert DRIVER_FILES, f"no driver modules found under {DRIVER_DIR}"
    names = {p.name for p in DRIVER_FILES}
    assert {"ext_eye_gaze.py", "fb_social.py", "htc_tracker.py"} <= names


@pytest.mark.parametrize("driver", DRIVER_FILES, ids=lambda p: p.name)
def test_no_driver_touches_the_session_wide_calls(driver: Path) -> None:
    """The rule, enforced on the source rather than remembered.

    `base_driver.py` is included in the sweep on purpose: the interface is not
    allowed to make these calls either, and a helper added there would be the
    obvious way to reintroduce the bug for every driver at once.
    """
    offending = _xr_calls(driver) & BACKEND_ONLY_CALLS

    assert not offending, (
        f"{driver.name} calls xr.{', xr.'.join(sorted(offending))}. "
        f"Both are session-wide and belong to the backend: attaching twice fails "
        f"with XR_ERROR_ACTIONSETS_ALREADY_ATTACHED and stops the backend binding "
        f"at all; syncing again with only this driver's action set deactivates "
        f"the controller actions for the rest of the frame. Publish the action "
        f"set as `gaze_action_set` and let the backend attach and sync it."
    )


def test_a_backend_still_makes_both_calls() -> None:
    """The counterpart. Somebody has to attach, or nothing tracks at all.

    Without this, deleting the calls from the backend would satisfy the test
    above perfectly.
    """
    backend = DRIVER_DIR.parent / "backends/backend_openxr.py"

    assert _xr_calls(backend) >= BACKEND_ONLY_CALLS, (
        "the OpenXR backend no longer attaches or syncs its action sets"
    )


def test_the_interface_declares_the_action_set_drivers_publish() -> None:
    """So the backend reads a field rather than probing for one.

    It was `getattr(self.eye_driver, "gaze_action_set", None)` in both backends
    -- code asking its own port whether it happens to have an attribute the port
    never mentioned.
    """
    pytest.importorskip("xr")
    from src.eye_tracking.base_driver import IEyeTrackingDriver

    assert hasattr(IEyeTrackingDriver, "gaze_action_set")
    assert IEyeTrackingDriver.gaze_action_set is None, (
        "the default must be None: a driver that uses no action set is normal"
    )


def test_every_registered_driver_satisfies_the_interface() -> None:
    """Including the attribute, before any of them has been initialised."""
    pytest.importorskip("xr")
    from src.eye_tracking.base_driver import IEyeTrackingDriver
    from src.eye_tracking.factory import EyeTrackingFactory

    EyeTrackingFactory.load_builtin_drivers()
    assert EyeTrackingFactory._registry, "no drivers registered"

    for driver_class in EyeTrackingFactory._registry:
        driver = driver_class()
        assert isinstance(driver, IEyeTrackingDriver)
        assert driver.gaze_action_set is None, (
            f"{driver_class.__name__} has an action set before initialize()"
        )
        assert driver.get_extension_name()
        assert isinstance(driver.get_priority(), int)


def test_the_priorities_that_decide_which_headsets_were_affected() -> None:
    """Pinned because the blast radius of the bug was a function of them.

    If the Khronos driver ever outranks the vendor ones, it is selected
    everywhere rather than only on hardware without a vendor extension.
    """
    pytest.importorskip("xr")
    from src.eye_tracking.ext_eye_gaze import EXTEyeGazeDriver
    from src.eye_tracking.fb_social import FBEyeTrackingSocialDriver
    from src.eye_tracking.htc_tracker import HTCEyeTrackingDriver

    assert FBEyeTrackingSocialDriver().get_priority() == 100
    assert HTCEyeTrackingDriver().get_priority() == 50
    assert EXTEyeGazeDriver().get_priority() == 10
