/// <reference lib="webworker" />
// The service worker, hand-written rather than generated (spec §4.5, §11).
//
// It exists because a push that nothing renders is not a notification: a Workbox
// `generateSW` bundle has no `push` listener, so every message the backend sent was
// delivered to the browser and dropped. Chrome eventually revokes a `userVisibleOnly`
// subscription that never shows anything, so the silence was also self-erasing.
//
// NO NAVIGATION MAY EVER BE ANSWERED FROM CACHE. A top-level navigation is the only thing
// that can complete a Cloudflare Access round-trip, so a cached one locks the visitor out
// for good — the edge never sees them, every API call comes back as the Access login page,
// and the reload meant to fix it is served from cache too. Under `generateSW` that took
// three settings to hold off; here it is structural, and stays that way only as long as
// this file registers no NavigationRoute and never calls createHandlerBoundToURL. The glob
// in vite.config.ts still excludes html so there is no shell to serve either.
// src/pwa/precache.test.ts guards both halves.
import { clientsClaim } from 'workbox-core';
import { precacheAndRoute } from 'workbox-precaching';

declare const self: ServiceWorkerGlobalScope & {
  __WB_MANIFEST: Parameters<typeof precacheAndRoute>[0];
};

precacheAndRoute(self.__WB_MANIFEST);

// registerType is 'autoUpdate': take over as soon as a new build lands, so the bundle a
// notification tap opens is the current one.
self.skipWaiting();
clientsClaim();

type Payload = { title?: string; body?: string; url?: string };

self.addEventListener('push', (event) => {
  // Anything can arrive here — a malformed body, or an empty push used by some services to
  // wake the worker. Throwing out of this handler is exactly what counts against the
  // subscription, so fall back to a generic notification rather than failing.
  let data: Payload = {};
  try {
    data = (event.data?.json() as Payload) ?? {};
  } catch {
    data = {};
  }
  const url = typeof data.url === 'string' ? data.url : '/me';
  event.waitUntil(
    self.registration.showNotification(data.title || 'ChoreKeeper', {
      body: data.body || '',
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      data: { url },
    }),
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data as { url?: string } | undefined)?.url ?? '/me';
  event.waitUntil(
    (async () => {
      // Reuse the installed window if it is already open — on iOS a second one cannot be
      // opened at all, and navigating the live client keeps the Access session warm.
      const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      for (const client of clients) {
        if ('focus' in client) {
          await client.focus();
          // navigate() only works on a client this worker controls. clientsClaim above
          // makes that the normal case, but a tab opened before the worker took over
          // would reject and swallow the focus we just did — leave it where it is.
          try {
            await client.navigate(url);
          } catch {
            /* focused is better than nothing */
          }
          return;
        }
      }
      await self.clients.openWindow(url);
    })(),
  );
});
