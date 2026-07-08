flowchart TD
    Start([Execute: python -m src.main]) --> Parse[argparse.ArgumentParser]
    
    %% Arguments
    Parse --> ArgConsent[--gdpr-consent<br/>(Action: store_true)]
    Parse --> ArgOutput[--output<br/>(Type: str, Default: 'Sessions')]
    Parse --> ArgSub[--subject-id<br/>(Type: str, Default: 'SUB_UNKN_01')]
    
    %% Validation
    ArgConsent --> ValConsent{Is True?}
    ValConsent -- No --> LogAbort[logger.error<br/>Launch aborted] --> Exit([sys.exit(1)])
    
    ValConsent -- Yes --> Topology[RuntimeCapabilityDiscovery.extract()]
    ArgOutput --> MergeConfig
    ArgSub --> MergeConfig
    Topology --> MergeConfig[Merge into Configuration Dicts]
    
    MergeConfig --> Instantiate[Instantiate TelemetryEngine]
    Instantiate --> EnforceID[engine.subject_metadata[...] = args.subject_id]
    
    EnforceID --> StartEngine[engine.start()]
    StartEngine --> End([Tracking Session Active])
    
    classDef input fill:#e1bee7,stroke:#8e24aa,stroke-width:2px;
    classDef check fill:#ffe0b2,stroke:#ff9800,stroke-width:2px;
    classDef fail fill:#ffcdd2,stroke:#f44336,stroke-width:2px;
    
    class ArgConsent,ArgOutput,ArgSub input;
    class ValConsent check;
    class LogAbort,Exit fail;