# src/eye_tracking/factory.py

import logging
from importlib import import_module

from src.eye_tracking.base_driver import IEyeTrackingDriver

logger = logging.getLogger(__name__)


class EyeTrackingFactory:
    """
    Capability factory responsible for instantiating the highest-fidelity biometric
    abstraction layer available in the runtime execution environment.
    """

    _registry: list[type[IEyeTrackingDriver]] = []
    _drivers_loaded: bool = False

    #: Modules whose import registers a driver. Listed here rather than imported
    #: at module scope so that a host missing one vendor's bindings degrades to
    #: "that driver is not offered" instead of failing the whole import.
    #:
    #: This does not yet make the factory importable without OpenXR at all:
    #: ``base_driver`` still does a hard ``import xr`` for its type references,
    #: so ``xr`` remains required to import this module. Cutting that last
    #: dependency means expressing the driver interface as a port that does not
    #: name vendor types, which is VRT-14.
    _DRIVER_MODULES: list[str] = [
        "src.eye_tracking.ext_eye_gaze",
        "src.eye_tracking.fb_social",
        "src.eye_tracking.htc_tracker",
    ]

    @classmethod
    def load_builtin_drivers(cls) -> None:
        """Import the bundled drivers so they self-register.

        Registration used to be a side effect of importing
        ``src.eye_tracking``, which meant it happened for anyone who touched
        anything in the package and not at all for anyone who imported
        ``factory`` directly. Making it an explicit, idempotent step puts the
        behaviour where it can be reasoned about -- and lets a caller register
        an out-of-tree driver before resolution without racing an import.
        """
        if cls._drivers_loaded:
            return
        cls._drivers_loaded = True
        for module_name in cls._DRIVER_MODULES:
            try:
                import_module(module_name)
            except ImportError as exc:
                # A driver whose bindings are absent on this host is not an
                # error: resolution simply will not offer it. Anything else
                # is a real defect and must not be swallowed silently.
                logger.debug(f"Eye-tracking driver {module_name} unavailable: {exc}")

    @classmethod
    def register_driver(cls, driver_class: type[IEyeTrackingDriver]) -> None:
        """
        Registers an eye-tracking class into the resolution pipeline.
        """
        if driver_class not in cls._registry:
            cls._registry.append(driver_class)
            # Sort globally to keep O(1) resolution cost during instantiation
            cls._registry.sort(key=lambda d: d().get_priority(), reverse=True)

    @classmethod
    def create_best_driver(cls, available_extensions: list[str]) -> IEyeTrackingDriver | None:
        """
        Evaluates the runtime topology against the driver priority matrix, returning
        an initialized instance of the best available tracker.
        """
        cls.load_builtin_drivers()
        logger.info(f"Resolving eye-tracking driver against extensions: {available_extensions}")
        for driver_class in cls._registry:
            driver_instance = driver_class()
            ext_name = driver_instance.get_extension_name()

            if ext_name in available_extensions:
                logger.info(
                    f"Biometric binding resolution: Selected {ext_name} (Priority {driver_instance.get_priority()})"
                )
                return driver_instance

        logger.warning(
            "No compatible biometric tracking hardware found. Defaulting to empty ocular structs."
        )
        return None
