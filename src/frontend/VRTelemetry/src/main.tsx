import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import './index.css'
// Side-effect import: applies the persisted/system dark-mode class to <html>
// before anything renders, so Login/Activation screens are themed too, not
// just the app shell that happens to import this store for its toggle button.
import './store/useThemeStore'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)