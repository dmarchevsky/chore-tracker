import { useState } from 'react';

/** Which inbox sections a parent has folded away, remembered per device.
 *
 * Sign-out does not clear localStorage (auth/AuthContext.tsx drops the cookie and nothing
 * else), so this survives a re-login as well as a reload — which is the whole point.
 */

/** Only the sections a parent has actually toggled.
 *
 * Anything absent follows the default its screen declares, so a default can be changed later
 * without fighting a value written months ago, and a section added later starts where its
 * code says rather than inheriting whatever its neighbour was left at.
 */
type Stored = Record<string, boolean>;

/** Storage throws outright in a locked-down browser, and a remembered preference must never
 *  be able to break the screen — so every read and write is guarded, as in theme.ts. */
function read(key: string): Stored {
  try {
    const raw = localStorage.getItem(key);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const entries = Object.entries(parsed as Record<string, unknown>);
    return Object.fromEntries(entries.filter(([, v]) => typeof v === 'boolean')) as Stored;
  } catch {
    return {};
  }
}

function write(key: string, value: Stored): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // A per-device convenience; if it can't be remembered, the screen still works.
  }
}

/** `defaults` is the open/closed state of a section nobody has touched yet. Pass a module
 *  constant, not an object literal built in render. */
export function useSectionState(key: string, defaults: Record<string, boolean>) {
  const [stored, setStored] = useState<Stored>(() => read(key));

  const isOpen = (id: string): boolean => stored[id] ?? defaults[id] ?? true;

  const toggle = (id: string): void =>
    setStored((prev) => {
      const next = { ...prev, [id]: !(prev[id] ?? defaults[id] ?? true) };
      write(key, next);
      return next;
    });

  return { isOpen, toggle };
}
