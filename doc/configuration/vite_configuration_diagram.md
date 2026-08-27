```mermaid
graph TD
    A[vite.config.ts] -->|Loads| B(Vite defineConfig)
    B -->|Uses Plugin| C(@vitejs/plugin-react)
    C -->|Enables| D[React JSX & Fast Refresh]
```