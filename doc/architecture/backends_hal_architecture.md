```mermaid
graph TD
    subgraph HAL ["Hardware Abstraction Layer (src.backends)"]
        RCD["RuntimeCapabilityDiscovery"]
        OHB["OpenXRHeadlessBackend"]
    end

    App ["Spatial Engine / Client"] -->|"Discovers Capabilities"| RCD
    App -->|"Initializes Context"| OHB
```