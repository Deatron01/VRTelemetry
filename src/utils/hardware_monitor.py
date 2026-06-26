import threading
import time
import psutil
import soundcard as sc
import numpy as np

class HardwareMonitor:
    """
    Monitors host CPU metrics and ambient voice amplitudes on a separate thread,
    preventing hardware delays from breaking the precision timeline.
    """
    def __init__(self):
        self.cpu_usage = 0.0
        self.voice_db = -60.0
        self.is_running = False
        self._thread = None
        self._mic_thread = None

    def start(self) -> None:
        self.is_running = True
        self._thread = threading.Thread(target=self._cpu_loop, daemon=True)
        self._thread.start()
        self._mic_thread = threading.Thread(target=self._audio_loop, daemon=True)
        self._mic_thread.start()

    def _cpu_loop(self) -> None:
        psutil.cpu_percent() # Clear initial state buffer
        while self.is_running:
            self.cpu_usage = psutil.cpu_percent(interval=None)
            time.sleep(0.5)

    def _audio_loop(self) -> None:
        try:
            # Binds default sound recording line descriptors safely
            with sc.default_microphone().recorder(samplerate=44100, channels=1) as mic:
                while self.is_running:
                    data = mic.record(numframes=1024)
                    rms = np.sqrt(np.mean(data**2)) if len(data) > 0 else 0.0
                    self.voice_db = float(20 * np.log10(rms + 1e-6))
        except Exception:
            self.voice_db = -60.0 # Standard fallback if hardware configuration blocks access

    def stop(self) -> None:
        self.is_running = False
        if self._thread:
            self._thread.join(timeout=1.0)