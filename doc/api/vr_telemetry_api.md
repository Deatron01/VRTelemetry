```mermaid
graph TD
    Client[Web Frontend / CLI] -->|HTTP Requests| FastAPI[FastAPI App App]
    FastAPI -->|Telemetry Upload| Telemetry[Telemetry Engine]
    FastAPI -->|SQLite Metadata| DB[(Sessions DB)]
    FastAPI -->|Auth/License Check| Central[Central Server]
    FastAPI -->|Local State| Cache[Local License Cache]
```