# ChoreKeeper

A chore tracker for one household, running on your own machine at home.

A parent writes down the chores. Each kid gets them on their phone, does the chore, and takes
a photo (or checks in, or just ticks a box) inside the time window. An AI model **running on
the home machine** looks at the photo and answers the specific questions the parent wrote —
"is the sink basin free of dishes?" — and says how sure it is. If it is confident, the chore
settles on its own. If it is not, or anything looks off, it lands in the parent's review
queue. Every pass and every miss writes a line in the money ledger, so the allowance
conversation is a statement instead of an argument.

The photos never leave the house. There is no account to sign up for, no app store, and no
company holding your family's pictures — see [Privacy](#privacy--what-leaves-the-house).

## How it works

1. **Parent defines a chore** — when it's due, who does it, what proof to send, what it's
   worth, and the list of checks the AI should answer.
2. **The kid gets it** on their phone, as an installed web app: today's list, "due in 40
   minutes", a big capture button.
3. **The kid submits proof** inside the window. The camera opens *inside the app* — no
   picking an old picture out of the gallery.
4. **The model checks it**, at home, in a few seconds.
5. **The parent reviews** anything uncertain, and can override any verdict at any time.
6. **The ledger records it** — money earned, money lost, payouts made. Append-only: a mistake
   is corrected by a reversing entry, never by quietly editing history.

Kids see *why* something failed, in their own language ("There are still two cups in the
sink"), which turns the app from a scorekeeper into a checklist. They see their own balance
and statement, and can dispute a verdict or ask to redo.

## What a chore can be

Three kinds of thing live in the chore list:

| Kind | What it is | Example |
|---|---|---|
| **Scheduled** | A recurring job with a due time and a window. Generates occurrences, earns or costs money. | "Kitchen counters, daily by 8:00pm" |
| **Standing** | A state a parent switches on and off. No due time, nothing to submit, no money — just a sentence that stays in force until it's switched back. | "Grounded until the missing assignments are in" |
| **Penalty** | A published price list the parent charges against when a rule gets broken, at a moment nobody scheduled. | "Bike left in the driveway — $5" |

Publishing the penalty list in advance is deliberate: a charge should never be the first time
a kid hears the price.

**How often:** daily, weekdays, weekends, a specific weekday, a day of the month, or a
one-off date. Each chore has a due time, a window that opens before it (so tomorrow's photo
can't be sent today), and a grace period — late but inside grace still passes, optionally at
a reduced amount.

**Who does it:** one named kid, rotating between kids on a weekly / biweekly / daily cycle,
first-come-claims-it, or everyone gets their own copy.

**What counts as proof:**

| Proof | What the kid does |
|---|---|
| **Photo** | Takes one or more photos, each with its own label — "sink close-up", "wide shot of the counters". Two labeled shots verify far better than one vague one. |
| **Location** | Taps "I'm here" inside a window; the app checks the distance to a fence the parent drew on a map. This is an active check-in, not background tracking — a phone browser cannot follow a kid around, and this one deliberately doesn't try. |
| **Photo + location** | Both. |
| **Acknowledgement** | Ticks it off. Honour system, still ledgered. |
| **None** | Parent verifies it themselves. |

**What it's worth:** an amount for doing it, optionally an amount for missing it, and a
multiplier for "late but inside grace". For chores a person has to grade — a report card, say
— the parent instead writes an ordered list of outcomes ("all A grades → +$100", "more than
one missing assignment → grounded until it's fixed") and picks one at review time. Those are
always graded by a human; the model is never asked to judge them.

## What the AI actually checks

The verification model is a **vision LLM running on your own hardware** — llama.cpp,
vLLM or Ollama, whatever you point it at. Nothing is sent to a model provider.

Instead of asking it "is the kitchen clean?", which nothing can answer reliably, the parent
writes a short checklist of yes/no questions:

> 1. Is the sink basin free of dishes, cups, pans and utensils?
> 2. Is the countertop immediately around the sink free of dirty dishes?
> 3. Is the visible area free of food waste or spills?

The model answers each one with **yes / no / unclear**, a confidence, and one sentence saying
what it can actually see. The verdict comes from the answers; the confidence is the weakest
link in the chain. Guardrails, all of them deliberate:

- **The model recommends, the parent decides.** Confident pass settles; confident fail
  settles; anything in between goes to the parent. Every kid-facing message says the parent
  has the final say, and override is one tap away.
- **It can only ever route to review, never auto-fail on suspicion.** A false accusation is
  worse than a missed cheat.
- **If the model is down, nobody loses money.** A timeout, a crash or unparseable output
  sends the chore to the parent's queue — never to a fail.
- **A bad photo asks for a retake.** Too dark, too blurry, wrong subject: the kid is told to
  take it again and the chore stays open. That's the difference between a tool and an
  adversary.
- **Anti-cheat, honestly scoped.** Photos are fingerprinted and compared against the last 120
  days, so yesterday's picture gets flagged. The server's clock is what counts, not the
  phone's. Gallery uploads are off by default, and when a parent turns them on for a chore,
  every one is flagged for review. A photo of a screen showing an old photo still gets past
  all of this — that's known, and it's what a parent's eyes are for.
- **Everything is logged**: the exact prompt sent, the raw response, the confidence, each
  check's answer. That's what lets you settle it at the dinner table.

Photo verification can also be turned off per chore — "model suggests, parent confirms
everything", or plain manual review. The product still works; it's just a very well-sorted
queue.

## Privacy — what leaves the house

Photos of your kids and your house are scored and stored at home. The database, the images
and the model all sit on your machine.

Two things touch the public internet, and nothing else does:

- **Cloudflare**, which carries the encrypted connection between your family's phones and
  your house, and handles the Google sign-in. It never sees chore content.
- **OpenStreetMap map tiles**, only in the admin screen where a parent draws a location
  fence, and only while that screen is open. No photo, name or chore data goes with it.

## Notifications

Kids get a push when a chore opens, thirty minutes before it is due, when a window closes on
them, and whenever a parent replies; parents get one when something is handed in and when
something is missed. It is Web Push from your own machine — no third-party service sees a
chore. Installing the app on the Home Screen is required (on iOS, by Apple), and the server
needs a VAPID keypair from `just vapid-keys`. Both walked through in
[docs/notifications.md](docs/notifications.md).

## Remote access

The app is reachable from anywhere without opening a single port on your router. A small
outbound-only tunnel connects your machine to Cloudflare, and Cloudflare Access — with Google
sign-in — sits in front of the whole app, for parent and kids alike. SSH, Postgres and the
model server stay on the LAN and are not reachable from outside; there is no remote operator
path at all.

If Cloudflare or Google is having a bad day, there's a break-glass admin password that only
answers on the LAN. Full setup and the security tradeoffs:
[docs/remote-access.md](docs/remote-access.md).

## Backups

`just backup` writes the database, the media volume and a manifest of row counts and per-child
balances to `backups/`. `just restore-verify <dir>` proves a backup restores into a clean
Postgres reproducing every balance to the cent — an untested backup is a rumour. Backups are
currently local and manual: [docs/restore.md](docs/restore.md).

---

# Running it

Requires `docker` + `docker compose`, [`uv`](https://docs.astral.sh/uv/), and
[`just`](https://github.com/casey/just).

```sh
just up          # build + start db, api, worker, proxy — no .env needed
just seed        # 1 household, admin "parent", three placeholder kids (identities printed)
just test        # pytest against the compose Postgres (exposed on :5432)
```

Open `http://localhost:5173` and pick who to sign in as — the dev stack has no Cloudflare
and no password. Touched `frontend/`? `just web-serve` rebuilds the bundle into the proxy
image; `just up` does not.

API is on `http://localhost:8088` (host `:8000` is reserved for an existing llama-server).
Interactive docs at `/docs` when `ENVIRONMENT=dev`.

## Two modes

There are exactly two compose files and no overlay between them.

| | dev — `docker-compose.yml` | prod — `docker-compose.prod.yml` |
|---|---|---|
| start | `just up` | `just prod-up` (needs `env.production`) |
| reachable from | the LAN only, `:5173` | the internet, via Cloudflare Tunnel |
| sign-in | pick a user, no password | Google, via Cloudflare Access |
| break-glass | none (the API 404s it) | admin password, LAN door only |
| data | `chorekeeper_dev_*` volumes, disposable | `chorekeeper_*` volumes, the real household |

They are separate compose projects, so `just up` cannot disturb a running production stack
— but both bind `:5173` and `:8088`, so stop one before starting the other. Deploying the
prod file under an orchestrator, plus the readiness audit:
[docs/deploy-dockhand.md](docs/deploy-dockhand.md).

## Layout

- `backend/` — FastAPI + async SQLAlchemy 2.0, managed by `uv`. Worker shares the image
  (`python -m app.worker`).
- `backend/migrations/` — Alembic (async env).
- `frontend/` — the React + Vite + Tailwind PWA (kid `/me/*` + admin `/admin/*`).
  `just web-dev` runs the Vite dev server (proxying `/api` to `:8088`); `just web-serve`
  builds it and serves it behind Caddy on `:5173`.
- `frontend/Caddyfile` — the front door: serves the PWA, proxies `/api`, sets the strict
  security headers. Built into the `proxy` image.
- `docker-compose.yml` — the dev stack: `db`, `api`, `worker`, `proxy`.
  `docker-compose.prod.yml` — the production stack, tunnel and all, in one file.

Full spec: [docs/chore-tracker-spec.md](docs/chore-tracker-spec.md). Development workflow
(worktrees, quality gates, push flow): [CLAUDE.md](CLAUDE.md).

## Auth notes

- **Sign-in is Google, via Cloudflare Access** (spec §12.1). Cloudflare authenticates the
  visitor at the edge; `GET /api/v1/auth/me` maps the verified `email` claim to a `users`
  row and mints the session, so there is no sign-in form. A parent adds a kid by entering
  their Google address under Kids — and in the Access policy, which is the half that
  actually lets them through the door.
- **First run:** a new database has no users, so the api bootstraps one on first start from
  `ADMIN_EMAIL` + `ADMIN_PASSWORD` (`python -m app.bootstrap`) — the household and the
  parent-admin, nothing else. Re-running it re-points the admin, which is the way back from
  a wrong `ADMIN_EMAIL`. `just seed` is dev-only demo data and refuses to run in prod.
- **Break-glass:** one local admin password (`POST /api/v1/auth/login`) for when Cloudflare
  or Google is unavailable. In the tunnel deployment it lives on a **LAN door** —
  `http://<home-ip>:5173`, a second Caddy site the tunnel has no route to — while the public
  hostname answers 404 for that path. Set the password from admin Settings.
- **Dev sign-in:** the dev stack sets `DEV_AUTH`, which adds `/auth/dev/users` +
  `/auth/dev/login` — the login page lists the household and you click a name. Those routes
  404 in every other configuration, break-glass 404s while `DEV_AUTH` is on, and the API
  refuses to start with `DEV_AUTH` under `ENVIRONMENT=prod` or alongside `CF_ACCESS_*`.
- Mutations require the `X-CSRF-Token` header echoing `csrf_token` from the login / `me`
  response. Session is an HTTP-only cookie (`ck_session`).
