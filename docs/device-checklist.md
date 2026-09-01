# Phase 5 device acceptance checklist

The PWA acceptance criteria (spec §14.5) can only be signed off on **real hardware** —
one iPhone and one Android — because `getUserMedia`, Home-Screen install, Web Push
delivery and the geofence automations all behave differently per platform.

## Setup

1. `just up` (backend) then `just web-serve` (builds + serves the PWA on `:5173`).
2. `just seed` — logs print the `parent` / `alice` / `bea` identities. On the LAN stack
   there is no Cloudflare Access, so sign in with the admin break-glass password the seed
   prints; testing the real Google sign-in means going through the tunnel hostname.
3. Put a VAPID keypair in `.env` (`VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY`,
   e.g. `npx web-push generate-vapid-keys`) and set `PUBLIC_BASE_URL` to the URL the
   phones will actually hit, then `just up` to reload. Without VAPID, push is logged as
   `skipped` and everything else still works.
4. Reach the box from each phone over the LAN or the Cloudflare tunnel. HTTPS is required
   for `getUserMedia` and install — use the tunnel hostname, or a trusted local cert. Over
   the tunnel each phone must be signed in to a Google account that is on **both** the
   Access policy and the app's Kids list ([remote-access.md](remote-access.md) step 5h).

## Run on **each** device (iPhone, Android) separately

- [ ] **Install to Home Screen.** Onboarding banner appears in a plain tab; after install
      it disappears. Android: browser menu → Install. iOS: Share → Add to Home Screen.
- [ ] **Camera capture.** Open a photo chore → live viewfinder → shutter fills each
      labeled slot → downscaled JPEG submits. A token-enabled chore shows the 2-digit
      number to hold in frame.
- [ ] **Camera permission recovery.** Deny camera once → the recovery screen explains how
      to re-enable and offers a reload (and the gallery picker if the chore allows it) —
      never a dead end.
- [ ] **Web Push.** Enable notifications (installed PWA only). Trigger a verdict from the
      admin inbox on a laptop → the push arrives on the phone, tapping it opens the chore.
      iOS delivers push **only** to the installed PWA — confirm it does nothing in a tab.
- [ ] **Offline queue.** Airplane mode → submit a photo → "saved, will send when online".
      Re-enable network → it uploads within a few seconds and the status updates.
- [ ] **Full happy path < 60 s.** From lock screen: open PWA → today's chore → capture →
      submit → see the verdict. Time it.

## Geofence automations (once each)

- [ ] **iPhone Shortcuts.** Automation → "When I arrive at [School]" → *Get Contents of
      URL* (POST, JSON body `{"lat":…, "lon":…, "accuracy":…}`) to the kid's
      `webhook_url` from the admin **Kids & money** panel. "Run Immediately" on. Confirm a
      real arrival flips the occurrence and the admin **Ops** page shows a fresh
      "last seen".
- [ ] **Android** — one of Tasker (Location profile → HTTP Request), MacroDroid (free
      tier), or the Home Assistant companion app (`zone.enter` trigger). Grant the
      battery-optimisation exemption or arrivals stop firing after a few weeks.

## Sign-off

Record the device models + OS versions and the happy-path time here when all boxes are
checked on both phones.
