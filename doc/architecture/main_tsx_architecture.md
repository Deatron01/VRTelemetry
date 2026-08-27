```mermaid
graph TD
    A[DOM Element: root] -->|ReactDOM.createRoot| B(React Root)
    B --> C[React.StrictMode]
    C --> D[App Component]
    D --> E[Global Styles: index.css]
```