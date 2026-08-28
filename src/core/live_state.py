import threading
import time

class LiveExperimentState:
    """
    Thread-safe side-channel for signals a passive hardware-polling backend cannot
    observe on its own: which scene is active, discrete event markers, haptic pulses
    the app fired, and the active target object's position (Category 7). Set via
    FastAPI endpoints from the running experiment; read once per frame by
    BiometricSynchronizer.push_frame(). Values default to legitimate "nothing is
    happening" states (0.0 / Menu), not fabricated readings.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self.scene_id = 1.0  # matches TelemetryFrame.create_empty()'s "Menu" default
        self.event_marker = 0.0
        self.haptic_left_intensity = 0.0
        self.haptic_right_intensity = 0.0
        self.target_obj_pos = (0.0, 0.0, 0.0)
        self._haptic_expiry_ns = {"left": 0, "right": 0}

    def set_scene(self, scene_id: float) -> None:
        with self._lock:
            self.scene_id = scene_id

    def set_event_marker(self, value: float) -> None:
        with self._lock:
            self.event_marker = value

    def trigger_haptic(self, side: str, intensity: float, duration_sec: float = 0.1) -> None:
        with self._lock:
            expiry = time.perf_counter_ns() + int(duration_sec * 1e9)
            if side == "left":
                self.haptic_left_intensity = intensity
                self._haptic_expiry_ns["left"] = expiry
            elif side == "right":
                self.haptic_right_intensity = intensity
                self._haptic_expiry_ns["right"] = expiry

    def set_target_position(self, x: float, y: float, z: float) -> None:
        with self._lock:
            self.target_obj_pos = (x, y, z)

    def snapshot(self) -> dict:
        """Read current state, auto-expiring haptic pulses whose duration has elapsed."""
        with self._lock:
            now_ns = time.perf_counter_ns()
            if now_ns > self._haptic_expiry_ns["left"]:
                self.haptic_left_intensity = 0.0
            if now_ns > self._haptic_expiry_ns["right"]:
                self.haptic_right_intensity = 0.0
            return {
                "scene_id": self.scene_id,
                "event_marker": self.event_marker,
                "haptic_left_intensity": self.haptic_left_intensity,
                "haptic_right_intensity": self.haptic_right_intensity,
                "target_obj_pos": self.target_obj_pos,
            }