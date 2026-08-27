```mermaid
flowchart TD
    A[Application Layer] -->|Calls methods| B(LocalLicenseCache)
    B -->|Persists / Queries| C[(SQLite Cache DB)]
    C -->|Returns Rows| B
    B -->|License State / Session / Queue| A
```
