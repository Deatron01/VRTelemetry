import time
import ctypes
from pathlib import Path
from typing import Optional

from src.core.interfaces import IVRBackend
from src.backends.backend_openxr import OpenXRBackend
from src.storage.parquet_writer import AsyncParquetWriter

# Windows-specific: Force high-resolution OS timers (1ms instead of default 15.6ms)
# Crucial for 90Hz (11.1ms) and 120Hz (8.33ms) precision.
try:
    winmm = ctypes.windll.winmm
except AttributeError:
    raise EnvironmentError("VRTelemetry requires a Windows operating system.")

class TelemetryEngine:
    """
    The main orchestrator. 
    Handles backend lifecycle, asynchronous storage, and the high-precision polling loop.
    """
    def __init__(self, target_hz: int = 90, output_dir: str = "Sessions"):
        self.target_hz = target_hz
        self.ideal_dt = 1.0 / self.target_hz
        self.is_running = False
        self.frames_recorded = 0
        
        # Prepare Storage
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        session_id = time.strftime("%Y%m%d_%H%M%S")
        self.parquet_path = out_path / f"vr_telemetry_{session_id}.parquet"
        self.writer = AsyncParquetWriter(output_path=self.parquet_path, target_hz=target_hz)
        
        # Determine Backend (For now, strictly OpenXR. Auto-discovery can be expanded here)
        self.backend: IVRBackend = OpenXRBackend()

    def start(self) -> None:
        """Initializes hardware and starts the strict timing loop."""
        print(f"[*] Initializing VRTelemetry Engine at {self.target_hz}Hz...")
        
        if not self.backend.initialize():
            print("[!] CRITICAL: Could not bind to any VR hardware. Exiting.")
            return

        self.writer.start()
        self.is_running = True
        
        # Elevate timer resolution for the duration of the run
        winmm.timeBeginPeriod(1)
        
        try:
            self._telemetry_loop()
        except KeyboardInterrupt:
            print("\n[*] Manual stop requested.")
        finally:
            self._shutdown()

    def _telemetry_loop(self) -> None:
        """
        The Zero-Loss Polling Loop.
        Uses a hybrid sleep/spin algorithm for microsecond precision without maxing out CPU.
        """
        print("[+] Telemetry loop active. Recording data... (Press Ctrl+C to stop)")
        
        next_frame_time = time.perf_counter()
        
        while self.is_running:
            # 1. Poll Hardware (GIL might be released depending on C-bindings)
            frame_data = self.backend.poll_frame(self.frames_recorded)
            
            # 2. Push to asynchronous storage (Non-blocking)
            self.writer.push(frame_data)
            
            self.frames_recorded += 1
            next_frame_time += self.ideal_dt
            
            # 3. Precision Timing
            now = time.perf_counter()
            time_to_sleep = next_frame_time - now
            
            if time_to_sleep > 0.002:
                # Sleep if we have more than 2ms to spare, yielding CPU to the OS
                time.sleep(time_to_sleep - 0.002)
            
            # Spin-lock for the remaining <2ms. This guarantees we hit the exact 
            # microsecond for the next frame, maintaining perfect Δt for AI tensors.
            while time.perf_counter() < next_frame_time:
                pass 

    def stop(self) -> None:
        self.is_running = False

    def _shutdown(self) -> None:
        """Gracefully tears down all threads and releases hardware hooks."""
        print("[*] Shutting down telemetry engine...")
        self.is_running = False
        
        winmm.timeEndPeriod(1) # Restore OS timer resolution
        
        self.writer.stop()
        self.backend.shutdown()
        
        print(f"[+] Shutdown complete. Total frames recorded: {self.frames_recorded}")
        print(f"[+] Parquet saved to: {self.parquet_path}")