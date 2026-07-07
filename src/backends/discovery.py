# src/backends/discovery.py

import logging
import xr
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class RuntimeCapabilityDiscovery:
    """
    Stateless evaluator for probing the active OpenXR runtime instance to extract
    hardware parameters and metadata required by standard REQ_4.1 - 4.32.
    """

    @staticmethod
    def extract_static_hardware_metadata() -> Dict[str, Any]:
        """
        Queries the OpenXR registry and returns a normalized dictionary representing
        system topologies and capability matrices.
        """
        metadata: Dict[str, Any] = {
            "tracking_system": "Unknown",
            "has_eye_tracking": 0,
            "has_face_tracking": 0,
            "has_body_tracking": 0,
            "openxr_runtime": "Unknown",
            "hmd_model": "Unknown"
        }

        try:
            available_extensions: List[str] = [
                ext.extension_name for ext in xr.enumerate_instance_extension_properties()
            ]

            # Biometric Support Evaluation
            if any(ext in available_extensions for ext in [
                "XR_EXT_eye_gaze_interaction",
                "XR_FB_eye_tracking_social",
                "XR_HTC_eye_tracker"
            ]):
                metadata["has_eye_tracking"] = 1

            if "XR_FB_face_tracking" in available_extensions or "XR_HTC_facial_tracking" in available_extensions:
                metadata["has_face_tracking"] = 1

            if "XR_HTCX_vive_tracker_interaction" in available_extensions:
                metadata["has_body_tracking"] = 1

            # Boot a temporary context strictly for identification, discarding immediately
            temp_instance = xr.create_instance(
                create_info=xr.InstanceCreateInfo(
                    application_info=xr.ApplicationInfo(
                        application_name="VRTelemetry_Prober",
                        api_version=xr.Version(1, 0, 0)
                    )
                )
            )

            props = xr.get_instance_properties(temp_instance)
            metadata["openxr_runtime"] = f"{props.runtime_name} {props.runtime_version}"

            sys_id = xr.get_system(
                temp_instance,
                xr.SystemGetInfo(xr.FormFactor.HEAD_MOUNTED_DISPLAY)
            )
            
            sys_props = xr.get_system_properties(temp_instance, sys_id)
            metadata["hmd_model"] = sys_props.system_name

            xr.destroy_instance(temp_instance)

        except xr.XrException as e:
            logger.warning(f"Runtime capabilities limited discovery fallback triggered: {e}")

        return metadata