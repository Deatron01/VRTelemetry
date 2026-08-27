```mermaid
flowchart TD
    A[Experiment Metadata Dict] -->|persist_experiment| B(DatabaseManager)
    B -->|Flatten & Map| C[SQLite Ledger]
    C -->|_get_connection| D[(vr_metadata.db)]
```
