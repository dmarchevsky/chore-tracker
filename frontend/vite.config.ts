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
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        // NO navigateFallback, deliberately. It served every navigation from the precached
        // shell, which means Cloudflare Access never saw a navigation — and Access can only
        // re-authenticate on a top-level navigation. Once the edge session ended, the app
        // kept loading from cache, every API call got a cross-origin redirect that `fetch`
        // cannot follow, and the user was locked out with no way to sign in again.
        //
        // Behind Access an offline shell buys almost nothing anyway: every screen needs an
        // API call, and those need both the network and a live edge session. What spec §11
        // actually requires — capturing and queueing a submission when the network drops
        // mid-use — happens in IndexedDB in an already-open tab and is unaffected.
        // Assets stay precached, so loads are still fast.
        //
        // Must be set explicitly: vite-plugin-pwa defaults it to 'index.html', so simply
        // omitting the option leaves the navigation route in place.
        navigateFallback: undefined,
      },
      manifest: {
        name: 'ChoreKeeper',
        short_name: 'Chores',
        start_url: '/me',
        scope: '/',
        display: 'standalone',
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
