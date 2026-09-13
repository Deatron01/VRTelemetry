import time
from dataclasses import dataclass


@dataclass(slots=True)
class TelemetryFrame:
    """
    Memory-isolated flat telemetry data layout utilizing __slots__ to enforce
    O(1) lookups and eliminate overhead from dynamic allocations inside the 120Hz loop.
    """

    frame_index: int
    timestamp_ns: int

    # HMD Spatial & Kinematic Telemetry
    hmd_pos_x: float
    hmd_pos_y: float
    hmd_pos_z: float
    hmd_rot_x: float
    hmd_rot_y: float
    hmd_rot_z: float
    hmd_rot_w: float
    hmd_tracking_valid: float

    # Left Controller Telemetry
    left_pos_x: float
    left_pos_y: float
    left_pos_z: float
    left_rot_x: float
    left_rot_y: float
    left_rot_z: float
    left_rot_w: float
    left_trigger: float
    left_grip: float
    left_joy_x: float
    left_joy_y: float
    left_tracking_valid: float

    # Right Controller Telemetry
    right_pos_x: float
    right_pos_y: float
    right_pos_z: float
    right_rot_x: float
    right_rot_y: float
    right_rot_z: float
    right_rot_w: float
    right_trigger: float
    right_grip: float
    right_joy_x: float
    right_joy_y: float
    right_tracking_valid: float

    # Unified Eye Tracking Telemetry
    left_eye_pos_x: float
    left_eye_pos_y: float
    left_eye_pos_z: float
    left_eye_rot_x: float
    left_eye_rot_y: float
    left_eye_rot_z: float
    left_eye_rot_w: float
    right_eye_pos_x: float
    right_eye_pos_y: float
    right_eye_pos_z: float
    right_eye_rot_x: float
    right_eye_rot_y: float
    right_eye_rot_z: float
    right_eye_rot_w: float
    eye_tracking_valid: float

    # Biometrics & Environment Telemetry
    left_pupil_size: float
    right_pupil_size: float
    heart_rate_bpm: float
    distance_to_boundary: float
    app_fps: float
    event_marker: float
    battery_hmd: float
    battery_left: float
    battery_right: float
    haptic_left_intensity: float
    haptic_right_intensity: float
    gaze_focal_distance: float
    voice_amplitude_db: float
    cpu_utilization: float
    gpu_utilization: float

    # Category 7: Virtuális Környezet Állapot (Added to fulfill specification sheet)
    scene_id: float
    target_obj_pos_x: float
    target_obj_pos_y: float
    target_obj_pos_z: float
    dist_to_target_left: float
    dist_to_target_right: float

    def to_tuple(self) -> tuple[float | int | None, ...]:
        """Flatten to a scalar tuple in the column order AsyncParquetWriter expects.

        The element order is a contract with ``AsyncParquetWriter._define_schema``:
        the two must stay in lockstep or frames land in the wrong columns, silently
        and irreversibly, in every session recorded afterwards. VRT-14 makes the
        schema and this projection derive from one declaration instead of two.
        """
        return (
            self.frame_index,
            self.timestamp_ns,
            # 1. HMD Kinematics
            self.hmd_pos_x,
            self.hmd_pos_y,
            self.hmd_pos_z,
            self.hmd_rot_x,
            self.hmd_rot_y,
            self.hmd_rot_z,
            self.hmd_rot_w,
            # 2. Left Controller
            self.left_pos_x,
            self.left_pos_y,
            self.left_pos_z,
            self.left_rot_x,
            self.left_rot_y,
            self.left_rot_z,
            self.left_rot_w,
            self.left_trigger,
            self.left_grip,
            self.left_joy_x,
            self.left_joy_y,
            # 3. Right Controller
            self.right_pos_x,
            self.right_pos_y,
            self.right_pos_z,
            self.right_rot_x,
            self.right_rot_y,
            self.right_rot_z,
            self.right_rot_w,
            self.right_trigger,
            self.right_grip,
            self.right_joy_x,
            self.right_joy_y,
            # 4. Eye Tracking Left
            self.left_eye_pos_x,
            self.left_eye_pos_y,
            self.left_eye_pos_z,
            self.left_eye_rot_x,
            self.left_eye_rot_y,
            self.left_eye_rot_z,
            self.left_eye_rot_w,
            # 5. Eye Tracking Right
            self.right_eye_pos_x,
            self.right_eye_pos_y,
            self.right_eye_pos_z,
            self.right_eye_rot_x,
            self.right_eye_rot_y,
            self.right_eye_rot_z,
            self.right_eye_rot_w,
            # 6. Validity Flags (Moved down to match schema definition exactly)
            self.hmd_tracking_valid,
            self.left_tracking_valid,
            self.right_tracking_valid,
            self.eye_tracking_valid,
            # 7. Biometrics
            self.left_pupil_size,
            self.right_pupil_size,
            self.heart_rate_bpm,
            # 8. Environment & System State
            self.distance_to_boundary,
            self.app_fps,
            self.event_marker,
            self.battery_hmd,
            self.battery_left,
            self.battery_right,
            self.haptic_left_intensity,
            self.haptic_right_intensity,
            self.gaze_focal_distance,
            self.voice_amplitude_db,
            self.cpu_utilization,
            self.gpu_utilization,
            # 9. Virtual Environment State
            self.scene_id,
            self.target_obj_pos_x,
            self.target_obj_pos_y,
            self.target_obj_pos_z,
            self.dist_to_target_left,
            self.dist_to_target_right,
        )

    @classmethod
    def create_empty(cls, frame_idx: int) -> "TelemetryFrame":
        """Generates a default vector to protect data sequence continuity during hardware drops."""
        return cls(
            frame_index=frame_idx,
            timestamp_ns=time.perf_counter_ns(),
            hmd_pos_x=0.0,
            hmd_pos_y=0.0,
            hmd_pos_z=0.0,
            hmd_rot_x=0.0,
            hmd_rot_y=0.0,
            hmd_rot_z=0.0,
            hmd_rot_w=1.0,
            hmd_tracking_valid=0.0,
            left_pos_x=0.0,
            left_pos_y=0.0,
            left_pos_z=0.0,
            left_rot_x=0.0,
            left_rot_y=0.0,
            left_rot_z=0.0,
            left_rot_w=1.0,
            left_trigger=0.0,
            left_grip=0.0,
            left_joy_x=0.0,
            left_joy_y=0.0,
            left_tracking_valid=0.0,
            right_pos_x=0.0,
            right_pos_y=0.0,
            right_pos_z=0.0,
            right_rot_x=0.0,
            right_rot_y=0.0,
            right_rot_z=0.0,
            right_rot_w=1.0,
            right_trigger=0.0,
            right_grip=0.0,
            right_joy_x=0.0,
            right_joy_y=0.0,
            right_tracking_valid=0.0,
            left_eye_pos_x=0.0,
            left_eye_pos_y=0.0,
            left_eye_pos_z=0.0,
            left_eye_rot_x=0.0,
            left_eye_rot_y=0.0,
            left_eye_rot_z=0.0,
            left_eye_rot_w=1.0,
            right_eye_pos_x=0.0,
            right_eye_pos_y=0.0,
            right_eye_pos_z=0.0,
            right_eye_rot_x=0.0,
            right_eye_rot_y=0.0,
            right_eye_rot_z=0.0,
            right_eye_rot_w=1.0,
            eye_tracking_valid=0.0,
            left_pupil_size=0.0,
            right_pupil_size=0.0,
            heart_rate_bpm=0.0,
            distance_to_boundary=-1.0,
            app_fps=0.0,
            event_marker=0.0,
            battery_hmd=-1.0,
            battery_left=-1.0,
            battery_right=-1.0,
            haptic_left_intensity=0.0,
            haptic_right_intensity=0.0,
            gaze_focal_distance=-1.0,
            voice_amplitude_db=-60.0,
            cpu_utilization=0.0,
            gpu_utilization=-1.0,
            scene_id=1.0,
            target_obj_pos_x=0.0,
            target_obj_pos_y=0.0,
            target_obj_pos_z=0.0,
            dist_to_target_left=0.0,
            dist_to_target_right=0.0,
        )


#: Column order for a flattened frame, matching `to_tuple()`'s actual output
#: order and `AsyncParquetWriter._define_schema()` -- NOT dataclass
#: declaration order. `to_tuple()` deliberately does not emit fields in the
#: order they're declared above: see its own "6. Validity Flags (Moved down
#: to match schema definition exactly)" comment, where the four
#: `*_tracking_valid` fields are pulled out of their sections and grouped
#: together after the eye-tracking fields. A first version of this constant
#: was `tuple(f.name for f in fields(TelemetryFrame))` -- declaration
#: order -- which silently mislabelled every field from `hmd_tracking_valid`
#: onward once zipped against a `to_tuple()` tuple. Caught before it shipped
#: to a plugin; the self-check below exists so the next drift is caught the
#: same way instead of shipping.
#:
#: Added for the VR Telemetry Hub plugin architecture
#: (`src/interfaces/api/event_router.py`,
#: `src/storage/broadcast_sink.py`): the Event Router receives the same
#: positional tuples `FrameSink.push()` does and needs field names to turn
#: one back into a JSON object for WebSocket subscribers, without importing
#: any producer-side acquisition code to get them.
FIELD_NAMES: tuple[str, ...] = (
    "frame_index",
    "timestamp_ns",
    "hmd_pos_x",
    "hmd_pos_y",
    "hmd_pos_z",
    "hmd_rot_x",
    "hmd_rot_y",
    "hmd_rot_z",
    "hmd_rot_w",
    "left_pos_x",
    "left_pos_y",
    "left_pos_z",
    "left_rot_x",
    "left_rot_y",
    "left_rot_z",
    "left_rot_w",
    "left_trigger",
    "left_grip",
    "left_joy_x",
    "left_joy_y",
    "right_pos_x",
    "right_pos_y",
    "right_pos_z",
    "right_rot_x",
    "right_rot_y",
    "right_rot_z",
    "right_rot_w",
    "right_trigger",
    "right_grip",
    "right_joy_x",
    "right_joy_y",
    "left_eye_pos_x",
    "left_eye_pos_y",
    "left_eye_pos_z",
    "left_eye_rot_x",
    "left_eye_rot_y",
    "left_eye_rot_z",
    "left_eye_rot_w",
    "right_eye_pos_x",
    "right_eye_pos_y",
    "right_eye_pos_z",
    "right_eye_rot_x",
    "right_eye_rot_y",
    "right_eye_rot_z",
    "right_eye_rot_w",
    "hmd_tracking_valid",
    "left_tracking_valid",
    "right_tracking_valid",
    "eye_tracking_valid",
    "left_pupil_size",
    "right_pupil_size",
    "heart_rate_bpm",
    "distance_to_boundary",
    "app_fps",
    "event_marker",
    "battery_hmd",
    "battery_left",
    "battery_right",
    "haptic_left_intensity",
    "haptic_right_intensity",
    "gaze_focal_distance",
    "voice_amplitude_db",
    "cpu_utilization",
    "gpu_utilization",
    "scene_id",
    "target_obj_pos_x",
    "target_obj_pos_y",
    "target_obj_pos_z",
    "dist_to_target_left",
    "dist_to_target_right",
)


def _verify_field_names_match_to_tuple() -> None:
    """Import-time self-check: FIELD_NAMES must name `to_tuple()`'s columns,
    in order. A silent mismatch here mislabels every field this application
    ever sends to a plugin without raising anything -- the exact failure
    class `to_tuple()`'s own docstring warns about for the Parquet schema,
    just one layer further out. Assigns a distinct sentinel per field (not
    just a count check) so a swapped pair is caught, not only a length
    drift -- a plain length check would not have caught the bug this
    replaced, since both orderings have the same 70 names.

    Raised, not asserted (`assert` is stripped under `python -O`) and raised
    at import rather than returned, matching this codebase's own rule
    (`src/core/exceptions.py`): a write path -- and every plugin's telemetry
    feed is one -- must not swallow a fault it can detect for free.
    """
    frame = TelemetryFrame.create_empty(0)
    for index, name in enumerate(FIELD_NAMES):
        if index < 2:  # frame_index / timestamp_ns keep their real (int) values
            continue
        setattr(frame, name, float(index) + 0.5)

    produced = frame.to_tuple()
    if len(produced) != len(FIELD_NAMES):
        raise AssertionError(
            f"FIELD_NAMES has {len(FIELD_NAMES)} entries but TelemetryFrame.to_tuple() "
            f"returns {len(produced)} -- they have drifted out of lockstep. Update "
            f"FIELD_NAMES to match to_tuple()'s actual column order."
        )
    for index in range(2, len(FIELD_NAMES)):
        expected = float(index) + 0.5
        if produced[index] != expected:
            raise AssertionError(
                f"FIELD_NAMES[{index}] = {FIELD_NAMES[index]!r} does not match the field "
                f"TelemetryFrame.to_tuple() actually puts at column {index}. FIELD_NAMES "
                f"has drifted out of lockstep with to_tuple() -- fix its order to match "
                f"that method's actual output before anything reads FIELD_NAMES again."
            )


_verify_field_names_match_to_tuple()
