import { useCallback, useEffect, useState } from 'react';

/** `auto` is not a third palette — it is "whatever the phone is set to", re-read live. */
export type Theme = 'light' | 'dark' | 'auto';

export const THEME_KEY = 'chorekeeper.theme';

/** The chrome around the page: matched to the palette so the phone's status bar follows. */
const CHROME = { dark: '#0f172a', light: '#f8fafc' } as const;

const DARK_QUERY = '(prefers-color-scheme: dark)';

const isTheme = (v: unknown): v is Theme => v === 'light' || v === 'dark' || v === 'auto';

/** The stored choice, or `auto`. Storage throws in a locked-down browser — never fatal. */
export function readTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    return isTheme(stored) ? stored : 'auto';
  } catch {
    return 'auto';
  }
}

function storeTheme(theme: Theme): void {
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    // A per-device convenience; if it can't be remembered, the session still works.
  }
}

/** What `auto` resolves to right now. */
function systemTheme(): 'light' | 'dark' {
  return window.matchMedia?.(DARK_QUERY).matches ? 'dark' : 'light';
}

/** Stamp the palette onto <html>, where index.css and the pre-paint script both look. */
export function applyTheme(theme: Theme): void {
  const resolved = theme === 'auto' ? systemTheme() : theme;
  document.documentElement.dataset.theme = resolved;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', CHROME[resolved]);
}

/** The current choice and a setter. While on `auto`, follows the OS as it changes. */
export function useTheme(): [Theme, (next: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(readTheme);

  useEffect(() => {
    applyTheme(theme);
    if (theme !== 'auto') return;
    const mq = window.matchMedia?.(DARK_QUERY);
    if (!mq) return;
    const onChange = () => applyTheme('auto');
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [theme]);

  const choose = useCallback((next: Theme) => {
    storeTheme(next);
    setTheme(next);
  }, []);

  return [theme, choose];
}
