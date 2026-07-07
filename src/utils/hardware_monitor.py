# src/utils/hardware_monitor.py

import threading
import time
import logging
from typing import Optional
import psutil

logger = logging.getLogger(__name__)

class HardwareMonitor:
    """
    Decoupled low-frequency hardware metric poller.
    Operates on an independent OS thread to continuously update CPU/Audio vectors
    without interrupting the OpenXR sub-millisecond precision loops.
    """

    def __init__(self, target_hz: int = 10):
        self.target_hz = target_hz
        self.sleep_interval = 1.0 / self.target_hz
        self.is_running = False
        
        # Thread-safe read variables using Python's GIL atomicity for floats
        self.cpu_usage: float = 0.0
        self.voice_db: float = -60.0
        
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Initializes the background daemon for system polling."""
        self.is_running = True
        self._thread = threading.Thread(
            target=self._poll_loop, 
            daemon=True, 
            name="HardwareMonitorDaemon"
        )
        self._thread.start()
        logger.info(f"Hardware subsystem monitor booted at {self.target_hz} Hz.")

    def _poll_loop(self) -> None:
        """
        Executes low-frequency system metric extraction.
        Forward Fill (Last-Known-Value) is naturally handled by simply exposing
        the variables to the BiometricSynchronizer.
        """
        # First call initializes the psutil interval counter
        psutil.cpu_percent(interval=None)
        
        while self.is_running:
            try:
                # Update host processor saturation estimation (Requirement DATA-2.63)
                self.cpu_usage = float(psutil.cpu_percent(interval=None)) / 100.0
                
                # Audio tracking stub (Dependent on OS-specific implementations, defaulted for specs)
                # Future expansion: Implement PyAudio capture for decibel analysis
                self.voice_db = -60.0 
                
            except Exception as e:
                logger.debug(f"Hardware poll misfire: {e}")
                
            time.sleep(self.sleep_interval)

    def stop(self) -> None:
        """Gracefully halts the hardware thread."""
        self.is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)