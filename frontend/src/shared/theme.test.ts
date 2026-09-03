import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { applyTheme, readTheme, THEME_KEY } from './theme';

/** jsdom has no matchMedia; every test says what the device is set to. */
function device(dark: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({ matches: dark, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  );
}

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
  device(false);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('readTheme', () => {
  it('follows the device until someone chooses otherwise', () => {
    expect(readTheme()).toBe('auto');
  });

  it('reads back a stored choice', () => {
    localStorage.setItem(THEME_KEY, 'light');
    expect(readTheme()).toBe('light');
  });

  it('ignores a value that is not a theme', () => {
    localStorage.setItem(THEME_KEY, 'chartreuse');
    expect(readTheme()).toBe('auto');
  });

  it('falls back rather than throwing when storage is unavailable', () => {
    // A private window, or a browser set to block site data — the app still has to run.
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied');
    });
    expect(readTheme()).toBe('auto');
  });
});

describe('applyTheme', () => {
  it('stamps the chosen palette on <html>', () => {
    applyTheme('light');
    expect(document.documentElement.dataset.theme).toBe('light');
    applyTheme('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('resolves auto against the device', () => {
    device(true);
    applyTheme('auto');
    expect(document.documentElement.dataset.theme).toBe('dark');

    device(false);
    applyTheme('auto');
    expect(document.documentElement.dataset.theme).toBe('light');
  });

  it('moves the browser chrome with the palette', () => {
    const meta = document.createElement('meta');
    meta.setAttribute('name', 'theme-color');
    document.head.append(meta);

    applyTheme('light');
    expect(meta.getAttribute('content')).toBe('#f8fafc');
    applyTheme('dark');
    expect(meta.getAttribute('content')).toBe('#0f172a');
    meta.remove();
  });
});
