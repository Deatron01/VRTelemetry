import threading
import time
import psutil

class HardwareMonitor:
    """
    A non-blocking daemon thread that polls CPU and RAM usage.
    It caches the values so the high-frequency telemetry loop can read them 
    in O(1) time without blocking the VR frame polling.
    """
    def __init__(self, polling_rate_hz: float = 2.0):
        self.polling_rate = 1.0 / polling_rate_hz
        self.is_running = False
        
        # Cached values
        self.cpu_percent = 0.0
        self.gpu_percent = 0.0  # Requires specific NVML/AMD bindings, left at 0 for now
        self.battery_hmd = 1.0
        
        self._thread = None

    def start(self) -> None:
        if self.is_running:
            return
            
        self.is_running = True
        # Initialize psutil (first call always returns 0.0)
        psutil.cpu_percent()
        
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def _monitor_loop(self) -> None:
        while self.is_running:
            try:
                # This call blocks for a split second, which is why it's on a separate thread
                self.cpu_percent = psutil.cpu_percent(interval=None)
                
                # Note: GPU polling via pynvml could be added here safely.
                
                time.sleep(self.polling_rate)
            except Exception as e:
                print(f"[!] Hardware Monitor Error: {e}")
                time.sleep(1.0) # Back off on error

    def get_latest_cpu(self) -> float:
        return self.cpu_percent
        
    def get_latest_gpu(self) -> float:
        return self.gpu_percent

    def stop(self) -> None:
        self.is_running = False
        if self._thread:
            self._thread.join(timeout=2.0)