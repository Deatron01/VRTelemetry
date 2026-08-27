```mermaid
graph TD
    Client[Desktop / Admin Client] -->|HTTP Requests| App[FastAPI app]
    App -->|Auth Management| AuthMgr[AuthManager]
    App -->|License Ops| LicenseMgr[LicenseManager]
    App -->|Data Ingestion| DataMgr[CentralDataManager]
    App -->|Admin UI Mount| Static[StaticFiles /admin-ui]
```
