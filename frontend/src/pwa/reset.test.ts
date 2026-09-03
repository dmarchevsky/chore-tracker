import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { resetApp } from './reset';

const reload = vi.fn();

beforeEach(() => {
  reload.mockClear();
  vi.stubGlobal('location', { reload });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function withWorkers(...unregisters: (() => Promise<boolean>)[]) {
  vi.stubGlobal('navigator', {
    serviceWorker: {
      getRegistrations: () => Promise.resolve(unregisters.map((unregister) => ({ unregister }))),
    },
  });
}

function withCaches(keys: string[]) {
  const del = vi.fn((_key: string) => Promise.resolve(true));
  vi.stubGlobal('caches', { keys: () => Promise.resolve(keys), delete: del });
  return del;
}

describe('resetApp', () => {
  it('unregisters every worker, empties every cache, and reloads', async () => {
    const a = vi.fn(() => Promise.resolve(true));
    const b = vi.fn(() => Promise.resolve(true));
    withWorkers(a, b);
    const del = withCaches(['assets-v1', 'workbox-precache']);

    await resetApp();

    expect(a).toHaveBeenCalledOnce();
    expect(b).toHaveBeenCalledOnce();
    expect(del.mock.calls.map((c) => c[0])).toEqual(['assets-v1', 'workbox-precache']);
    expect(reload).toHaveBeenCalledOnce();
  });

  it('leaves IndexedDB alone — that is where unsent photos live', async () => {
    // offlineQueue.ts stores captured-but-unsent submissions there. Clearing the app's
    // cached code must never throw away work a kid actually did.
    const deleteDatabase = vi.fn();
    vi.stubGlobal('indexedDB', { deleteDatabase });
    withWorkers();
    withCaches(['assets-v1']);

    await resetApp();

    expect(deleteDatabase).not.toHaveBeenCalled();
  });

  it('still reloads when the APIs are missing', async () => {
    // An old browser, or a page not served over https — the reload is the part that
    // matters and it cannot be conditional on the cleanup having anything to clean.
    vi.stubGlobal('navigator', {});
    vi.stubGlobal('caches', undefined);

    await resetApp();

    expect(reload).toHaveBeenCalledOnce();
  });

  it('still reloads when a step throws', async () => {
    withWorkers(() => Promise.reject(new Error('denied')));
    const del = withCaches(['assets-v1']);

    await resetApp();

    // A failure unregistering must not cost the cache sweep, nor the reload.
    expect(del).toHaveBeenCalledOnce();
    expect(reload).toHaveBeenCalledOnce();
  });
});
