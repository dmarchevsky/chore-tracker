import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

// All assets are bundled locally — no CDN fonts or scripts (spec §5).
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: 'auto',
      workbox: {
        // No navigation may EVER be answered from cache. A top-level navigation is the
        // only thing that can complete a Cloudflare Access round-trip, so a cached one
        // locks the visitor out for good: the edge never sees them, every API call comes
        // back as the Access login page, and the reload that is supposed to fix it is
        // served from cache too — a refresh loop that cannot end.
        //
        // Two settings, because dropping `html` from the glob is not on its own enough:
        // `directoryIndex` defaults to 'index.html' and resolves a request for "/" onto a
        // precached shell anyway. Removing navigateFallback missed exactly that — "/",
        // which is the URL a bookmark or a shared link uses. (workbox's `cleanURLs`, which
        // would try "/me.html", is not a generateSW option; it is harmless here because
        // once no HTML is precached there is nothing for it to find.)
        globPatterns: ['**/*.{js,css,svg,png,woff2}'],
        directoryIndex: null,
        // Must be set explicitly: vite-plugin-pwa defaults it to 'index.html', so simply
        // omitting the option leaves the navigation route in place.
        navigateFallback: undefined,
        //
        // The cost, stated plainly: with no network the app does not load. It already did
        // not — the manifest's start_url is /me, which was never precached, so only the
        // bare domain ever opened offline. Behind Access an offline shell buys nothing
        // regardless, since every screen needs an API call and a live edge session. What
        // spec §11 actually requires — queueing a submission when the network drops
        // mid-use — is IndexedDB in an already-open tab and is untouched. Assets stay
        // precached, so loads are still fast.
      },
      manifest: {
        name: 'ChoreKeeper',
        short_name: 'Chores',
        start_url: '/me',
        scope: '/',
        display: 'standalone',
        // Deliberately fixed to the night palette: the manifest is baked at build time and
        // the splash is a one-time surface, so it cannot follow the per-device choice the
        // app makes at runtime (src/shared/theme.ts). It matches what an unstamped document
        // renders as, which src/index.css defines as night.
        background_color: '#0f172a',
        theme_color: '#0f172a',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: { '/api': 'http://localhost:8088' },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.ts'],
    css: false,
  },
});
