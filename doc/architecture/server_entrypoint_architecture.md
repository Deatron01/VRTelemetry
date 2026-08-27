```mermaid
graph TD
    A[server_entrypoint.py] -->|Calls setup_logging| B(src.utils.logger)
    A -->|Hosts FastAPI app| C(src.main.app)
    A -->|Runs server via| D[uvicorn.run]
```
