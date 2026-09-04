import { describe, expect, it } from 'vitest';
// The build config and the worker, as text. Nothing in a jsdom suite can see a workbox
// route take effect, and this exact regression has shipped once already believing it was
// fixed — so read the code that decides it.
import config from '../../vite.config.ts?raw';
import swSource from '../sw.ts?raw';

// The comments in sw.ts explain the very rules asserted below and name the APIs they
// forbid, so match against the code alone.
const sw = swSource.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

describe('the service worker precache', () => {
  it('does not precache the shell', () => {
    // A precached index.html is served for any navigation ending in "/" — including the
    // bare domain, which is what a bookmark uses. Cloudflare Access can only sign someone
    // in on a real navigation, so a cached one locks them out and loops the tab.
    const glob = /globPatterns:\s*\[([^\]]*)\]/.exec(config)?.[1] ?? '';
    expect(glob).not.toMatch(/html/);
  });

  it('registers no route that could answer a navigation', () => {
    // Under injectManifest there are no directoryIndex/navigateFallback defaults to pin —
    // the shell comes back only if this file asks for it, so assert that it never does.
    expect(sw).not.toMatch(/NavigationRoute/);
    expect(sw).not.toMatch(/createHandlerBoundToURL/);
    expect(sw).not.toMatch(/navigateFallback/);
  });

  it('renders the pushes it is subscribed to', () => {
    // A userVisibleOnly subscription that shows nothing is eventually revoked by Chrome,
    // which is what a generated worker (no push listener) silently did.
    expect(sw).toMatch(/addEventListener\('push'/);
    expect(sw).toMatch(/showNotification/);
    expect(sw).toMatch(/addEventListener\('notificationclick'/);
  });
});
