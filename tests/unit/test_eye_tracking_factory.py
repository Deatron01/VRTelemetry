# tests/unit/test_eye_tracking_factory.py

import pytest
from src.eye_tracking.factory import EyeTrackingFactory
from src.eye_tracking.base_driver import IEyeTrackingDriver

class MockLowPriorityDriver(IEyeTrackingDriver):
    def get_extension_name(self) -> str: return "XR_MOCK_low"
    def get_additional_extensions(self) -> list: return []
    def get_priority(self) -> int: return 10
    def initialize(self, i, s, a): pass
    def populate_frame(self, f, t): pass
    def shutdown(self): pass

class MockHighPriorityDriver(IEyeTrackingDriver):
    def get_extension_name(self) -> str: return "XR_MOCK_high"
    def get_additional_extensions(self) -> list: return []
    def get_priority(self) -> int: return 50
    def initialize(self, i, s, a): pass
    def populate_frame(self, f, t): pass
    def shutdown(self): pass

@pytest.fixture(autouse=True)
def setup_factory():
    """Inject mock drivers into the registry for isolated unit testing."""
    original_registry = EyeTrackingFactory._registry.copy()
    EyeTrackingFactory._registry.clear()
    
    EyeTrackingFactory.register_driver(MockLowPriorityDriver)
    EyeTrackingFactory.register_driver(MockHighPriorityDriver)
    
    yield
    
    # Restore original registry to prevent test pollution
    EyeTrackingFactory._registry = original_registry

def test_factory_resolves_highest_priority():
    """
    If multiple biometric extensions are available in the runtime environment, 
    the factory must bind the one with the highest fidelity (priority integer).
    """
    available_extensions = ["XR_MOCK_low", "XR_MOCK_high", "XR_MND_headless"]
    
    driver = EyeTrackingFactory.create_best_driver(available_extensions)
    
    assert driver is not None
    assert isinstance(driver, MockHighPriorityDriver)
    assert driver.get_priority() == 50

def test_factory_resolves_fallback():
    """
    If the high-priority extension is missing, it must safely fall back 
    to the lower-priority implementation.
    """
    available_extensions = ["XR_MOCK_low", "XR_MND_headless"]
    
    driver = EyeTrackingFactory.create_best_driver(available_extensions)
    
    assert driver is not None
    assert isinstance(driver, MockLowPriorityDriver)
    assert driver.get_priority() == 10

def test_factory_returns_none_if_unsupported():
    """
    If no registered extensions are present in the OpenXR runtime, 
    the factory must return None to allow standard non-biometric tracking to continue.
    """
    available_extensions = ["XR_MND_headless", "XR_EXT_hand_tracking"]
    
    driver = EyeTrackingFactory.create_best_driver(available_extensions)
    
    assert driver is None