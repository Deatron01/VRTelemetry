# tests/unit/test_discovery.py

import pytest
from unittest.mock import patch, MagicMock
from src.backends.discovery import RuntimeCapabilityDiscovery

@patch("src.backends.discovery.xr")
def test_discovery_no_biometrics(mock_xr):
    """
    Validates that the discovery engine correctly identifies an environment 
    lacking any advanced tracking capabilities, defaulting all biometric flags to 0.
    """
    # Mock extension enumeration returning only basic headless support
    mock_ext = MagicMock()
    mock_ext.extension_name = "XR_MND_headless"
    mock_xr.enumerate_instance_extension_properties.return_value = [mock_ext]

    metadata = RuntimeCapabilityDiscovery.extract_static_hardware_metadata()

    assert metadata["has_eye_tracking"] == 0
    assert metadata["has_face_tracking"] == 0
    assert metadata["has_body_tracking"] == 0

@patch("src.backends.discovery.xr")
def test_discovery_with_htc_biometrics(mock_xr):
    """
    Validates that the presence of XR_HTC_eye_tracker correctly flips 
    the capability flag in the static dataset matrix.
    """
    mock_ext1 = MagicMock()
    mock_ext1.extension_name = "XR_MND_headless"
    mock_ext2 = MagicMock()
    mock_ext2.extension_name = "XR_HTC_eye_tracker"
    mock_ext3 = MagicMock()
    mock_ext3.extension_name = "XR_HTC_facial_tracking"
    
    mock_xr.enumerate_instance_extension_properties.return_value = [mock_ext1, mock_ext2, mock_ext3]

    metadata = RuntimeCapabilityDiscovery.extract_static_hardware_metadata()

    assert metadata["has_eye_tracking"] == 1
    assert metadata["has_face_tracking"] == 1
    assert metadata["has_body_tracking"] == 0