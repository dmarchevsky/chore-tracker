// Capture-and-queue: if the network drops mid-submit, stash the multipart pieces in
// IndexedDB and retry on reconnect. School wifi is bad; this matters (spec §11, §14.5).
// Photos are stored as ArrayBuffers so they survive structured-clone round trips.

import { api, ApiError } from '../api/client';

const DB_NAME = 'chorekeeper';
const STORE = 'pending-submissions';

export interface QueueInput {
  occurrenceId: string;
  note: string;
  source: 'camera' | 'gallery';
  files: Blob[];
  geo: { lat: number; lon: number; accuracy: number } | null;
}

interface StoredSubmission {
  id: string;
  occurrenceId: string;
  note: string;
  source: 'camera' | 'gallery';
  files: { data: ArrayBuffer; type: string }[];
  geo: { lat: number; lon: number; accuracy: number } | null;
  createdAt: number;
}

function hasIdb(): boolean {
  try {
    return typeof indexedDB !== 'undefined' && indexedDB !== null;
  } catch {
    return false; // some browsers throw on access in restricted contexts
  }
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE)) {
        req.result.createObjectStore(STORE, { keyPath: 'id' });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function tx<T>(
  mode: IDBTransactionMode,
  fn: (s: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await openDb();
  try {
    return await new Promise<T>((resolve, reject) => {
      const req = fn(db.transaction(STORE, mode).objectStore(STORE));
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  } finally {
    db.close();
  }
}

function blobToBuffer(b: Blob): Promise<ArrayBuffer> {
  if (typeof b.arrayBuffer === 'function') return b.arrayBuffer();
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(fr.result as ArrayBuffer);
    fr.onerror = () => reject(fr.error);
    fr.readAsArrayBuffer(b);
  });
}

export async function enqueue(input: QueueInput): Promise<void> {
  if (!hasIdb()) return;
  const files = await Promise.all(
    input.files.map(async (b) => ({ data: await blobToBuffer(b), type: b.type || 'image/jpeg' })),
  );
  const item: StoredSubmission = {
    id: crypto.randomUUID(),
    occurrenceId: input.occurrenceId,
    note: input.note,
    source: input.source,
    files,
    geo: input.geo,
    createdAt: Date.now(),
  };
  await tx('readwrite', (s) => s.put(item));
}

export async function pendingCount(): Promise<number> {
  if (!hasIdb()) return 0;
  return (await _pending()).length;
}

async function _pending(): Promise<StoredSubmission[]> {
  return (await tx<StoredSubmission[]>('readonly', (s) => s.getAll())).sort(
    (a, b) => a.createdAt - b.createdAt,
  );
}

async function remove(id: string): Promise<void> {
  await tx('readwrite', (s) => s.delete(id));
}

function buildForm(item: StoredSubmission): FormData {
  const fd = new FormData();
  fd.set('note', item.note);
  fd.set('source', item.source);
  if (item.geo) fd.set('geo', JSON.stringify(item.geo));
  item.files.forEach((f, i) =>
    fd.append('files', new Blob([f.data], { type: f.type }), `photo-${i}.jpg`),
  );
  return fd;
}

/** POST one item. Returns true if it left the queue (sent, or a 4xx rejection). */
async function trySend(item: StoredSubmission): Promise<boolean> {
  try {
    await api.post(`/occurrences/${item.occurrenceId}/submissions`, buildForm(item));
    await remove(item.id);
    return true;
  } catch (e) {
    if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
      await remove(item.id); // server rejected it — stop retrying forever
      return true;
    }
    return false; // offline / 5xx — keep it for the next flush
  }
}

let flushing = false;
export async function flushQueue(): Promise<{ sent: number; kept: number }> {
  if (flushing || !hasIdb()) return { sent: 0, kept: 0 };
  flushing = true;
  let sent = 0;
  let kept = 0;
  try {
    for (const item of await _pending()) {
      if (await trySend(item)) sent++;
      else kept++;
    }
  } finally {
    flushing = false;
  }
  return { sent, kept };
}

export function startAutoFlush(): () => void {
  const onOnline = () => void flushQueue();
  window.addEventListener('online', onOnline);
  void flushQueue();
  return () => window.removeEventListener('online', onOnline);
}
