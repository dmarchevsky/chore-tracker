import { describe, expect, it } from 'vitest';
// The shell exactly as it ships, read as text — index.html is not part of the module graph.
import html from '../index.html?raw';

describe('index.html', () => {
  it('carries no inline script, because the proxy serves script-src self', () => {
    // A theme-stamping <script> lived here once and was silently refused by the browser in
    // every deployment: frontend/Caddyfile sets script-src 'self' with no unsafe-inline,
    // nonce or hash. jsdom does not enforce CSP, so no rendering test can catch this —
    // reading the file is the only guard there is.
    const inline = [...html.matchAll(/<script\b([^>]*)>/g)].filter((m) => !/\bsrc=/.test(m[1]));
    expect(inline).toHaveLength(0);
  });

  it('still loads the bundle', () => {
    expect(html).toMatch(/<script type="module" src="[^"]+"><\/script>/);
  });
});
