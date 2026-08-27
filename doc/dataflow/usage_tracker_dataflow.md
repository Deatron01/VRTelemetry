```mermaid
graph TD
    A[App Component] -->|log_event| B(UsageTracker)
    B -->|Insert Event| C[(SQLite Database)]
```
