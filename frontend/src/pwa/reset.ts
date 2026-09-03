// The in-app equivalent of clearing the site's data, for a device whose cached copy has
// gone bad. It exists because the alternative is talking a kid through iOS Settings →
// Safari → Advanced → Website Data, which is not a thing that happens.
//
// A service worker that answers navigations out of cache can strand a visitor completely:
// Cloudflare Access can only re-authenticate on a top-level navigation, and if the cache
// answers those instead of the network, no amount of retrying will ever sign anyone in.
// That exact bug is fixed (the current sw.js registers no navigation route), but the class
// of it is worth having an escape hatch for.

/** Never touched. offlineQueue.ts keeps captured-but-unsent submissions in IndexedDB —
 *  photos a kid actually took. This clears code and assets, not their work. */

async function unregisterWorkers(): Promise<void> {
  const regs = (await navigator.serviceWorker?.getRegistrations?.()) ?? [];
  await Promise.all(regs.map((r) => r.unregister()));
}

async function emptyCaches(): Promise<void> {
  if (typeof caches === 'undefined') return;
  const keys = await caches.keys();
  await Promise.all(keys.map((k) => caches.delete(k)));
}

/** Drop the service worker and every cached asset, then reload from the network.
 *
 * Each step is isolated: this runs on a device that is already misbehaving, and one
 * missing or throwing API must not stop the rest — least of all the reload, which is the
 * part that actually gets the visitor moving again.
 */
export async function resetApp(): Promise<void> {
  for (const step of [unregisterWorkers, emptyCaches]) {
    try {
      await step();
    } catch {
      /* nothing here is worth failing over; the reload still has to happen */
    }
  }
  window.location.reload();
}
