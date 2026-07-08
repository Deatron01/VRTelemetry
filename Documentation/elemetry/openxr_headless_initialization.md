sequenceDiagram
    participant Engine as TelemetryEngine
    participant XRBackend as OpenXRHeadlessBackend
    participant OpenXR as OpenXR API (xr)
    participant Display as OS Window Manager

    Engine->>XRBackend: initialize()
    
    XRBackend->>OpenXR: xrEnumerateInstanceExtensionProperties()
    note over OpenXR: Must verify XR_MND_headless is supported
    
    XRBackend->>OpenXR: xrCreateInstance(extensions=["XR_MND_headless", ...])
    OpenXR-->>XRBackend: XrInstance handle
    
    XRBackend->>OpenXR: xrGetSystem(XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY)
    OpenXR-->>XRBackend: XrSystemId
    
    note over XRBackend, Display: CRITICAL DIFFERENCE: No Swapchains or Graphics Binding required!
    
    XRBackend->>OpenXR: xrCreateSession(systemId)
    OpenXR-->>XRBackend: XrSession handle
    
    XRBackend->>OpenXR: xrCreateReferenceSpace(XR_REFERENCE_SPACE_TYPE_STAGE)
    OpenXR-->>XRBackend: XrSpace (Stage/Room-Scale)
    
    XRBackend->>OpenXR: xrCreateActionSet()
    note over OpenXR: Bind Hand Tracking & Gaze Actions
    XRBackend->>OpenXR: xrAttachSessionActionSets()
    
    XRBackend->>OpenXR: xrBeginSession()
    OpenXR-->>XRBackend: XR_SUCCESS
    
    XRBackend-->>Engine: return True