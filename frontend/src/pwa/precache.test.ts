import { describe, expect, it } from 'vitest';
// The build config as text. Nothing in a jsdom suite can see a workbox default take
// effect, and this exact regression has shipped once already believing it was fixed —
// so read the settings that decide it.
import config from '../../vite.config.ts?raw';

describe('the service worker precache', () => {
  it('does not precache the shell', () => {
    // A precached index.html is served for any navigation ending in "/" — including the
    // bare domain, which is what a bookmark uses. Cloudflare Access can only sign someone
    // in on a real navigation, so a cached one locks them out and loops the tab.
    const glob = /globPatterns:\s*\[([^\]]*)\]/.exec(config)?.[1] ?? '';
    expect(glob).not.toMatch(/html/);
  });

  it('pins the defaults that would put the shell back', () => {
    // directoryIndex resolves "/" onto index.html on its own, whatever the glob says, and
    // navigateFallback would serve it for every navigation. Both are on by default.
    expect(config).toMatch(/directoryIndex:\s*null/);
    expect(config).toMatch(/navigateFallback:\s*undefined/);
  });
});
