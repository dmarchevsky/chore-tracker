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
      // A hand-written service worker (src/sw.ts), because push notifications need a
      // `push` listener and a generated one has none. injectManifest only substitutes the
      // precache list into that file; everything else in it is ours.
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      injectManifest: {
        // No HTML in the precache. A precached index.html is served for any navigation
        // ending in "/" — including the bare domain, which is what a bookmark uses.
        // Cloudflare Access can only sign someone in on a real navigation, so a cached one
        // locks them out and loops the tab. Under injectManifest the other half of that
        // guard is structural: sw.ts registers no navigation route at all.
        //
        // The cost, stated plainly: with no network the app does not load. It already did
        // not — the manifest's start_url is /me, which was never precached, so only the
        // bare domain ever opened offline. Behind Access an offline shell buys nothing
        // regardless, since every screen needs an API call and a live edge session. What
        // spec §11 actually requires — queueing a submission when the network drops
        // mid-use — is IndexedDB in an already-open tab and is untouched. Assets stay
        // precached, so loads are still fast.
        globPatterns: ['**/*.{js,css,svg,png,woff2}'],
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
