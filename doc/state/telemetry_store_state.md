```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Loaded : loadSession()
    state Loaded {
        [*] --> Paused
        Paused --> Playing : togglePlayback()
        Playing --> Paused : togglePlayback()
    }
```
