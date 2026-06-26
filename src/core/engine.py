import time
import ctypes
from pathlib import Path
from src.backends import discover_active_backend
from src.storage.parquet_writer import AsyncParquetWriter
from src.utils.hardware_monitor import HardwareMonitor
from src.utils.logger import logger
from src.core.exceptions import HardwareBindingError

try:
    winmm = ctypes.windll.winmm
except AttributeError:
    raise EnvironmentError("OS Kernel Platform Conflict: VRTelemetry requires a Windows host environment.")

class TelemetryEngine:
    """
    Core orchestrator loop execution context. Governs timing precision down to
    sub-millisecond limits to support stable time-series matrix generation.
    """
    def __init__(self, target_hz: int = 90, output_dir: str = "Sessions"):
        self.target_hz = target_hz
        self.ideal_dt = 1.0 / target_hz
        self.is_running = False
        self.frames_recorded = 0
        
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        self.session_id = time.strftime("%Y%m%d_%H%M%S")
        
        self.parquet_path = out_path / f"vr_telemetry_{self.session_id}.parquet"
        self.writer = AsyncParquetWriter(output_path=self.parquet_path, target_hz=target_hz)
        self.hardware = HardwareMonitor()
        self.backend = None

    def start(self) -> None:
        self.backend = discover_active_backend()
        self.hardware.start()
        self.writer.start()
        self.is_running = True
        
        # Stabilize system clock limits across host scheduling pools
        winmm.timeBeginPeriod(1)
        
        try:
            self._loop()
        except KeyboardInterrupt:
            print("\n[*] Execution execution loop interrupted manually.")
        finally:
            self._teardown()

    def _loop(self) -> None:
        next_frame_time = time.perf_counter()
        while self.is_running:
            frame_data = self.backend.poll_frame(self.frames_recorded)
            
            # Inject cached low-frequency system metrics safely without blocking the timeline
            frame_data.cpu_utilization = self.hardware.cpu_usage
            frame_data.voice_amplitude_db = self.hardware.voice_db
            
            self.writer.push(frame_data)
            self.frames_recorded += 1
            next_frame_time += self.ideal_dt
            
            # Hybrid Sleep/Spin Execution Strategy
            now = time.perf_counter()
            time_to_sleep = next_frame_time - now
            if time_to_sleep > 0.002:
                time.sleep(time_to_sleep - 0.002)
            while time.perf_counter() < next_frame_time:
                pass

    def _teardown(self) -> None:
        self.is_running = False
        winmm.timeEndPeriod(1)
        self.hardware.stop()
        self.writer.stop()
        if self.backend:
            self.backend.shutdown()
        print(f"[+] Operational log finalized. Frames output: {self.frames_recorded}")