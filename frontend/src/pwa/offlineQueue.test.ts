import 'fake-indexeddb/auto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';

const { post } = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return { ...actual, api: { ...actual.api, post } };
});

const { enqueue, pendingCount, flushQueue } = await import('./offlineQueue');

function input(occ = 'occ-1') {
  return {
    occurrenceId: occ,
    note: 'done',
    source: 'camera' as const,
    files: [new Blob(['fake-jpeg-bytes'], { type: 'image/jpeg' })],
    geo: null,
  };
}

beforeEach(async () => {
  post.mockReset();
  await new Promise((res) => {
    const del = globalThis.indexedDB.deleteDatabase('chorekeeper');
    del.onsuccess = del.onerror = del.onblocked = () => res(null);
  });
});

afterEach(() => vi.clearAllMocks());

describe('offline queue', () => {
  it('keeps items while the network is down, then drains on reconnect', async () => {
    await enqueue(input());
    await enqueue(input());
    expect(await pendingCount()).toBe(2);

    post.mockRejectedValue(new TypeError('Failed to fetch'));
    expect(await flushQueue()).toEqual({ sent: 0, kept: 2 });
    expect(await pendingCount()).toBe(2);

    post.mockReset();
    post.mockResolvedValue(undefined);
    const r = await flushQueue();
    expect(r.sent).toBe(2);
    expect(await pendingCount()).toBe(0);
  });

  it('drops an item the server rejects with a 4xx (window closed)', async () => {
    await enqueue(input());
    post.mockRejectedValue(new ApiError(409, 'occurrence is missed, not open'));
    const r = await flushQueue();
    expect(r.sent).toBe(1);
    expect(await pendingCount()).toBe(0);
  });

  it('no-ops without IndexedDB', async () => {
    const real = globalThis.indexedDB;
    // @ts-expect-error simulate a restricted context
    delete globalThis.indexedDB;
    try {
      await enqueue(input());
      expect(await pendingCount()).toBe(0);
      expect(await flushQueue()).toEqual({ sent: 0, kept: 0 });
    } finally {
      globalThis.indexedDB = real;
    }
  });
});
