# tests/unit/test_backend_steamvr.py
"""The SteamVR eye-tracking capability probe queries the right property.

`SteamVROverlayBackend.poll_frame` used to check gaze support with
`Prop_HasCamera_Bool` -- the passthrough-camera flag, unrelated to eye
tracking, and not a property every SteamVR runtime answers for every
device. On hardware that does not answer it, the runtime raises
`TrackedPropertyError: TrackedProp_UnknownProperty`, which the code correctly
attributes to `eye_support_probe` and survives -- but the survival is the
problem: it happened on *every* frame of every session, permanently zeroing
`eye_tracking_valid` regardless of whether the headset actually supports gaze
interaction.

`Prop_SupportsXrEyeGazeInteraction_Bool` is the property that actually answers
"can this device do eye tracking". These tests pin the fix at the seam that
broke: the exact property queried, and that a runtime which still rejects it
(an older SteamVR, or hardware with nothing to report) degrades to a counted
fault rather than corrupting or crashing the frame.

The backend's other collaborators (`vr_system`, `vr_chaperone`) are faked
rather than driven through `openvr.init()`: standing up a real OpenVR context
needs a runtime and a headset, and the property this bug lives in has nothing
to do with pose enumeration or the chaperone boundary.
"""

from __future__ import annotations

import openvr
import pytest

from src.backends.backend_steamvr import SteamVROverlayBackend


class _FakePose:
    """A tracked-device pose that is simply not valid, which every helper here
    is happy to receive: it keeps the HMD/controller kinematics branches out
    of the way of the one property call these tests care about."""

    bPoseIsValid = False


class _FakeChaperone:
    """Stands in for `openvr.IVRChaperone()` so `poll_frame` never has to
    construct one against a context that was never initialized."""

    def getPlayAreaSize(self):
        return True, 2.0, 2.0


class _FakeVRSystem:
    """Enough of `openvr.IVRSystem` for `poll_frame` to run end to end without
    touching the native runtime.

    Args:
        eye_probe_result: What `getBoolTrackedDeviceProperty` returns for the
            eye-tracking capability probe specifically.
        eye_probe_exception: If set, raised instead -- simulating a runtime
            that rejects the property outright, as SteamVR does today.
    """

    def __init__(self, *, eye_probe_result=False, eye_probe_exception=None):
        self.bool_property_calls: list[tuple[int, int]] = []
        self._eye_probe_result = eye_probe_result
        self._eye_probe_exception = eye_probe_exception

    def getDeviceToAbsoluteTrackingPose(self, _universe, _seconds, count):
        return [_FakePose() for _ in range(count)]

    def getFloatTrackedDeviceProperty(self, _index, _prop):
        # HMD battery, read unconditionally each frame; its value is not what
        # these tests are about, so any float that does not raise will do.
        return 100.0

    def getBoolTrackedDeviceProperty(self, index, prop):
        self.bool_property_calls.append((index, prop))
        if self._eye_probe_exception is not None:
            raise self._eye_probe_exception
        return self._eye_probe_result

    def getTrackedDeviceIndexForControllerRole(self, _role):
        return openvr.k_unTrackedDeviceIndexInvalid


def _backend(vr_system: _FakeVRSystem) -> SteamVROverlayBackend:
    backend = SteamVROverlayBackend()
    backend.vr_system = vr_system
    backend.vr_chaperone = _FakeChaperone()
    return backend


def test_the_eye_probe_queries_gaze_interaction_support_not_camera_presence():
    """The property that actually means "this device can do eye tracking".

    `Prop_HasCamera_Bool` answers a different question (does the HMD have a
    passthrough camera) and is what the probe used to send -- pinned here as
    the property it must send instead.
    """
    vr_system = _FakeVRSystem(eye_probe_result=True)
    frame = _backend(vr_system).poll_frame(0)

    assert vr_system.bool_property_calls == [
        (openvr.k_unTrackedDeviceIndex_Hmd, openvr.Prop_SupportsXrEyeGazeInteraction_Bool)
    ]
    assert frame.eye_tracking_valid == 1.0


def test_a_headset_reporting_no_gaze_support_is_not_a_fault():
    """A `False` answer is data, not a failure -- the property call succeeded."""
    backend = _backend(_FakeVRSystem(eye_probe_result=False))
    frame = backend.poll_frame(0)

    assert frame.eye_tracking_valid == 0.0
    assert "eye_support_probe" not in backend.faults.counts


def test_a_runtime_that_rejects_the_property_is_counted_not_crashed():
    """The exact failure from the session log this fix is for.

    `TrackedProp_UnknownProperty` from `getBoolTrackedDeviceProperty` must
    still land as one counted `eye_support_probe` fault with
    `eye_tracking_valid` at 0.0 -- the same graceful degradation VRT-13 built
    -- rather than propagating out of `poll_frame` and ending the session.
    """
    backend = _backend(
        _FakeVRSystem(eye_probe_exception=openvr.OpenVRError("TrackedProp_UnknownProperty"))
    )

    frame = backend.poll_frame(0)

    assert frame.eye_tracking_valid == 0.0
    assert backend.faults.counts["eye_support_probe"] == 1


@pytest.mark.parametrize("exc", [ValueError("bad ctypes call"), OSError("native call failed")])
def test_the_other_property_faults_the_probe_already_guarded_still_work(exc):
    """The property swap must not narrow what the probe tolerates."""
    backend = _backend(_FakeVRSystem(eye_probe_exception=exc))

    frame = backend.poll_frame(0)

    assert frame.eye_tracking_valid == 0.0
    assert backend.faults.counts["eye_support_probe"] == 1
