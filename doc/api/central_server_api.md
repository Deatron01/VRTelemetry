```mermaid
graph TD;
    Client[Desktop/Client App] -->|/auth/*| AuthMgr[AuthManager]
    Client -->|/license/*| LicenseMgr[LicenseManager]
    Client -->|/data/*| DataMgr[CentralDataManager]
    Admin[Admin Dashboard] -->|/admin/* (require_admin)| Server[FastAPI Server]
    Server --> AuthMgr
    Server --> LicenseMgr
    Server --> DataMgr
```