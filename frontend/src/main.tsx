import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { applyTheme, readTheme } from './shared/theme';
import './index.css';

// Before the first render, so the signed-out screens get the viewer's palette too — they
// have no ThemeToggle to apply it, and the CSP (script-src 'self', frontend/Caddyfile)
// rules out doing this from an inline script in index.html. Until this runs the document
// is unstamped, which src/index.css defines as night.
applyTheme(readTheme());

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
