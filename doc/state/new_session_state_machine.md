```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Recording : handleStart() [gdpr_consent == true]
    Recording --> Idle : handleStop()
```