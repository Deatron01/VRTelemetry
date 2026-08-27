```mermaid
graph TD
    A[DOM Root Element] -->|Target| B[ReactDOM.createRoot]
    B --> C[React.StrictMode]
    C --> D[App Component]
    D --> E[index.css Styles]
```
