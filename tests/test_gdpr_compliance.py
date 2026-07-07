import pytest
from src.core.engine import TelemetryEngine
from src.core.exceptions import GDPRConsentError

def test_engine_gdpr_consent_missing_throws_exception():
    """Validates that running the engine without explicit consent immediately aborts tracking via exception."""
    with pytest.raises(GDPRConsentError):
        TelemetryEngine(target_hz=90, output_dir="TestSessions", gdpr_consent=False)

def test_engine_gdpr_consent_granted_initializes():
    """Validates that running the engine with explicit consent initializes normally."""
    try:
        engine = TelemetryEngine(target_hz=90, output_dir="TestSessions", gdpr_consent=True)
        assert engine.gdpr_consent is True
    except GDPRConsentError:
        pytest.fail("TelemetryEngine crashed unexpectedly when GDPR consent was provided.")