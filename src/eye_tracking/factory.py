# src/eye_tracking/factory.py

import logging
from typing import List, Optional, Type

from src.eye_tracking.base_driver import IEyeTrackingDriver

logger = logging.getLogger(__name__)

class EyeTrackingFactory:
    """
    Capability factory responsible for instantiating the highest-fidelity biometric 
    abstraction layer available in the runtime execution environment.
    """
    
    _registry: List[Type[IEyeTrackingDriver]] = []

    @classmethod
    def register_driver(cls, driver_class: Type[IEyeTrackingDriver]) -> None:
        """
        Registers an eye-tracking class into the resolution pipeline.
        """
        if driver_class not in cls._registry:
            cls._registry.append(driver_class)
            # Sort globally to keep O(1) resolution cost during instantiation
            cls._registry.sort(key=lambda d: d().get_priority(), reverse=True)

    @classmethod
    def create_best_driver(cls, available_extensions: List[str]) -> Optional[IEyeTrackingDriver]:
        """
        Evaluates the runtime topology against the driver priority matrix, returning
        an initialized instance of the best available tracker.
        """
        print(f"DEBUG: Runtime reports extensions: {available_extensions}")
        logger.info(f"DEBUG: Available extensions: {available_extensions}")
        for driver_class in cls._registry:
            driver_instance = driver_class()
            ext_name = driver_instance.get_extension_name()
            
            if ext_name in available_extensions:
                logger.info(f"Biometric binding resolution: Selected {ext_name} (Priority {driver_instance.get_priority()})")
                return driver_instance
                
        logger.warning("No compatible biometric tracking hardware found. Defaulting to empty ocular structs.")
        return None