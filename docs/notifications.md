# Notifications — installing the app and turning them on

ChoreKeeper reaches phones through **Web Push**: the notification is sent from your own
machine to the phone's push service and rendered by the installed app. No third-party
notification service ever sees a chore title — only an encrypted blob it cannot read (spec
§4.5, §12).

Two things have to be true before a single notification arrives:

1. the server has a **VAPID keypair** (below — without it every send is logged `skipped`), and
2. the phone has ChoreKeeper **installed** and has said yes to notifications.

---

## 1. Install the app

**Notifications will not work from a browser tab on iOS.** Apple delivers Web Push only to an
app on the Home Screen (spec §14.5). Android and desktop are more forgiving, but the app asks
everyone to install anyway so there is one thing to explain, not three.

**iPhone / iPad — Safari only.** Chrome and Firefox on iOS cannot install a web app.

1. Open ChoreKeeper in **Safari**.
2. Tap the **Share** button (the square with the arrow) at the bottom.
3. Scroll down and tap **Add to Home Screen**, then **Add**.
4. Close Safari and open ChoreKeeper from the new Home Screen icon.

**Android — Chrome.**

1. Open ChoreKeeper in Chrome.
2. Chrome usually offers **Install app** in a banner; otherwise open the **⋮** menu and choose
   **Install app** (older versions say *Add to Home screen*).
3. Open it from the Home Screen or app drawer.

**Desktop — Chrome or Edge.** Click the install icon (a monitor with an arrow) at the right of
the address bar, or **⋮ → Cast, save and share → Install page as app**.

You can tell it worked: the kid's **Settings** screen says *Installed on your Home Screen*
rather than *Running in a browser tab*.

## 2. Turn notifications on

Open ChoreKeeper **from the installed icon**, not a browser tab, then:

- **Kid:** the gear icon → **Reminders** → **Turn on notifications**.
- **Parent:** **Settings** → **Notifications** → **Turn on notifications**.

The phone asks once whether to allow notifications; say yes. The card then reads *Notifications
are on for this device*, and a **Turn off** button appears next to it.

A parent's card also has **Send a test**, which pushes a notification to that parent's own
devices and says what happened — how many devices it reached, or why it reached none. Press it
first whenever someone reports that notifications stopped: it separates a server with no VAPID
keys from a phone that never subscribed from a push service that refused the message, which
from the phone all look identical.

This is **per device**. A kid with a phone and an iPad has to do it on both, and each gets its
own copy of every notification.

If the phone was told "no" at some point, the card says so and offers no button — a refusal
cannot be undone from inside the page. Clear it in **iOS Settings → Notifications →
ChoreKeeper**, or Chrome's **Site settings → Notifications**, then come back.

## What gets sent

| Who | When | Lands on |
|---|---|---|
| Kid | a chore's window opens | that chore |
| Kid | 30 minutes before it is due, if still not handed in | that chore |
| Kid | the window closed without a check-in | that chore |
| Kid | a parent approves, rejects or asks for a redo — carrying the parent's note | that chore |
| Parent | a chore is handed in and needs a look | the review screen |
| Parent | a chore was missed | the review screen |

Tapping one opens the app on the thing it is about.

Two deliberate quiet spots: an **unassigned** ("anyone") chore nudges nobody, because there is
no one person it belongs to — but a parent is still told when it is missed. And a chore already
handed in is never nudged at T-30.

Every send — successful or not — is written to the notification log, whether or not any phone
was subscribed.

## 3. Set up the server side (once)

Web Push needs a VAPID keypair. Without one the app still runs; sends are recorded as
`skipped` and nothing reaches a phone.

```
just vapid-keys
```

It prints two lines and writes nothing. Paste them into `.env` (dev) or `env.production`
(prod), then restart both services so the API and the worker see them:

```
docker compose up -d api worker              # dev
docker compose -f docker-compose.prod.yml up -d api worker   # prod
```

**The keys are permanent.** Every existing subscription is bound to the public key that
created it, so rotating the pair silently breaks every phone in the house until each one turns
notifications off and on again. Back them up with the rest of your secrets.

## Troubleshooting

**Press Send a test first** (Parent → **Settings** → **Notifications**). It tells you in one
click which layer is broken, and its answers map onto the statuses below.

**Then check the log.** Parent → **Ops** → *Recent notifications*. Each row carries a status:

| Status | Meaning |
|---|---|
| `sent` | it left the building — anything after this is the phone or its push service |
| `no_subs` | that person has no device subscribed; they never turned it on, or turned it off |
| `skipped` | the server has no VAPID keys (step 3) |
| `failed` | the push service rejected it; the error is on the row |

A subscription the push service reports as gone (404/410) is deleted automatically, so a phone
that was wiped or reinstalled stops producing failures on its own.

**"Turn on notifications" seems to do nothing.** The card now says *This ChoreKeeper has no
notification keys* when that is the reason — step 3 was skipped, or the keys were pasted but
the api and worker were not restarted. Before that message existed the button silently
returned you to the same screen, which is the same thing this looks like on an old bundle.

**Nothing at all on an iPhone.** Almost always the app was opened from Safari rather than the
Home Screen icon, or it was "installed" from Chrome, which on iOS cannot. The Reminders card
says *needs install* in both cases.

**Nothing on the dev stack from another device.** `http://192.168.x.x:5173` is **not a secure
context**, so the browser refuses to register a service worker at all — no worker, no push.
Only `http://localhost:5173` on the machine itself, or the HTTPS Cloudflare hostname of the
production stack, can exercise notifications. This is a browser rule, not a ChoreKeeper one.

**The app looks stale, or notifications stopped after an update.** It is an installed PWA with
a service worker; a normal reload can still hand you the old bundle. Hard-reload
(Ctrl+Shift+R), or sign out and use **App stuck? Reset it** on the sign-in screen, which
unregisters the worker, clears the caches and reloads. After a reset, turn notifications back
on.

**A notification arrives but tapping it does nothing useful.** It opens the app at the chore or
review screen it refers to; if the session has expired behind Cloudflare Access, the tap lands
on the Access sign-in first and continues afterwards.
