import { useEffect, useState } from 'react';

/** Anything narrower than Tailwind's `md` — where the two-pane layouts collapse to one column. */
export const PHONE = '(max-width: 767.98px)';

/**
 * Whether the viewport matches `query` right now, following it as the window resizes.
 * Falls back to `false` where `matchMedia` is missing (jsdom), so tests see the wide layout.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia?.(query).matches ?? false);

  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return;
    setMatches(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setMatches(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [query]);

  return matches;
}
