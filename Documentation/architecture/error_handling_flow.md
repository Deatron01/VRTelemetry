flowchart TD
    %% Events
    Run[Main Loop Running]
    Event_KBI([User presses Ctrl+C<br/>KeyboardInterrupt])
    Event_GDPR([GDPR Consent Revoked<br/>GDPRConsentError])
    Event_Panic([Hardware/API Panic<br/>Unhandled Exception])

    %% Handlers
    Run --> Event_KBI
    Run --> Event_GDPR
    Run --> Event_Panic

    subgraph Teardown_Sequence ["Graceful Degradation & Teardown"]
        direction TB
        LogKBI[Log: 'Interrupted manually by operator']
        LogGDPR[Log: 'Compliance violation terminated tracking']
        LogCrit[Log: 'CRITICAL Unhandled framework panic']
        
        TeardownRoutine[Execute engine._teardown()]
        Exit1([sys.exit(1)])
        Exit0([sys.exit(0)])
    end

    Event_KBI --> LogKBI
    Event_GDPR --> LogGDPR
    Event_Panic --> LogCrit

    LogKBI --> TeardownRoutine
    LogGDPR --> TeardownRoutine
    
    %% Critical panic might bypass safe teardown if context is completely lost, but standard try/except attempts it
    LogCrit --> TeardownRoutine 

    TeardownRoutine --> Exit0
    
    %% Isolated boot failure
    Boot[Bootstrapper: main.py] --> BootCheck{GDPR Flag<br/>Passed?}
    BootCheck -- No --> AbortBoot[Log Error & Abort]
    AbortBoot --> Exit1
    
    classDef error fill:#ffcdd2,stroke:#f44336,stroke-width:2px;
    classDef warn fill:#fff9c4,stroke:#fbc02d,stroke-width:2px;
    classDef safe fill:#c8e6c9,stroke:#4caf50,stroke-width:2px;
    
    class Event_GDPR,Event_Panic,Exit1,AbortBoot error;
    class Event_KBI,LogKBI,LogGDPR,LogCrit warn;
    class TeardownRoutine,Exit0 safe;