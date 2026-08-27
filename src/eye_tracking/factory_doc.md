### Purpose
The factory module provides dynamic capability resolution for eye-tracking drivers in the runtime execution environment. It enables the system to evaluate hardware and extension availability, automatically selecting and instantiating the highest-priority compatible biometric abstraction layer.

### Key Components / Key Classes / Key Exports
- **`EyeTrackingFactory`**: Manages driver registration, priority sorting, and instantiation of the best available eye-tracking driver based on runtime extensions.

### Integration Points
Interacts directly with implementations of `IEyeTrackingDriver` by registering them, querying their extension names and priorities, and returning an instantiated driver instance to callers within the broader eye-tracking subsystem.
