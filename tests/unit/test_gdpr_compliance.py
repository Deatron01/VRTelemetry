# tests/unit/test_gdpr_compliance.py

import pytest
from src.core.engine import TelemetryEngine
from src.core.exceptions import GDPRConsentError
from src.backends.discovery import RuntimeCapabilityDiscovery

def test_engine_initialization_requires_consent():
    """
    Validates Requirement 2.50: Hardware tracking systems must throw a 
    fatal GDPRConsentError if instantiated without explicit user approval.
    """
    with pytest.raises(GDPRConsentError, match="Explicit user GDPR consent missing"):
        TelemetryEngine(output_dir="Tests/Temp", gdpr_consent=False)

def test_engine_runtime_consent_revocation(monkeypatch):
    """
    Validates Requirement 2.50: The tracking sequence must immediately 
    abort if consent is dynamically revoked during an active biometric session.
    """
    # 1. Boot Engine with explicit consent
    hardware_metadata = RuntimeCapabilityDiscovery.extract_static_hardware_metadata()
    engine = TelemetryEngine(
        output_dir="Tests/Temp",
        gdpr_consent=True,
        hardware_metadata=hardware_metadata,
        subject_metadata={"M-IV_Static_Metadata": {"subject_id": "TEST"}}
    )
    
    # 2. Mock the OpenXR poll to simulate active frames
    class MockBackend:
        def poll_frame(self, index):
            from src.core.datatypes import TelemetryFrame
            return TelemetryFrame.create_empty(index)
        
    engine.backend = MockBackend()
    engine.is_running = True
    
    # 3. Simulate a mid-session consent revocation
    engine.gdpr_consent = False
    
    assert not engine.gdpr_consent
    
    # 4. Attempt to cycle the main loop, expecting an immediate structural abort
    with pytest.raises(GDPRConsentError, match="Consent revoked during active sampling window"):
        engine._loop()