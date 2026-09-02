# Production deployment — DockHand

ChoreKeeper deploys as **one compose file**: [../docker-compose.prod.yml](../docker-compose.prod.yml).
It is one of the project's two compose files: this one is production, and
`docker-compose.yml` is the dev stack (`just up` — LAN only, passwordless sign-in, no
tunnel). There is no overlay between them and they share nothing, so deploying this changes
nothing about local development. `just prod-up` runs exactly this file with
`--env-file env.production`.

Topology, security model and every Cloudflare console step are [remote-access.md](remote-access.md).
This document covers only what is DockHand-specific, plus the readiness audit.

---

## The stack

| Service | Image / build | Publishes | Role |
|---|---|---|---|
| `db` | `postgres:17.6` (pinned) | `127.0.0.1:5432` | data; operator psql from the host only |
| `api` | `build: ./backend` | `127.0.0.1:8088` | FastAPI; runs `alembic upgrade head` before uvicorn |
| `worker` | `build: ./backend` | — | scheduler ticks + verification queue |
| `proxy` | `build: ./frontend` | `${LAN_DOOR_PORT:-5173}` → container `:81` | Caddy front door; `:80` (tunnel door) stays unpublished |
| `cloudflared` | `cloudflare/cloudflared:2026.8.3` (pinned) | — | sole ingress, outbound-only to Cloudflare's edge |

Volumes `db_data` and `media_data` are named and owned by project `chorekeeper-prod`, so
they survive recreations and cannot collide with a dev `chorekeeper` project on the same host.

`ENVIRONMENT=prod`, `COOKIE_SECURE=true` and `TRUST_PROXY_HEADERS=true` are **pinned in the
compose file**, not read from the environment — the production stack cannot be downgraded
to dev mode by a stray variable. Every secret is a `${VAR:?}` guard: a missing one fails the
deploy loudly instead of booting with a default.

## DockHand stack setup

1. **Stack → source:** this git repo (any branch you deploy from; `main`).
2. **Compose path:** `docker-compose.prod.yml`. Builds happen on the Docker agent from the
   checked-out repo (`./backend`, `./frontend` are repo-root-relative — keep the file at
   the root).
3. **Environment:** copy [../env.production.example](../env.production.example), fill it in,
   and paste the values into the stack's environment (or host the filled `env.production`
   on the agent for manual runs — it is gitignored; never commit it). The `:?` guards make
   a missing variable fail the deploy with a named error.
4. **First deploy against a fresh volume** — a brand-new database has **no household and
   no users**, and nothing creates them automatically. The worker ticks quietly until one
   exists. Set `ADMIN_PASSWORD` (12+ characters) in the stack environment, then bootstrap
   once from the host:
   ```sh
   docker compose -f docker-compose.prod.yml exec api python -m app.seed
   ```
   That creates the household, the parent-admin with **your** `ADMIN_PASSWORD` as its
   break-glass password, and placeholder kids. The seed **refuses to run** under
   `ENVIRONMENT=prod` without `ADMIN_PASSWORD` rather than planting the dev default, which
   is published in this repo and would be a working admin login for anyone on the wifi.

   Then, in the app: rename or deactivate the placeholder kids and add the real ones by
   Google address, and check the admin's own address (the `ADMIN_EMAIL` migration only
   stamps emails onto users that already exist, so it matters when upgrading an existing
   dev database, not on a fresh install). Every kid also needs their address on the Access
   policy — [remote-access.md](remote-access.md) §5h.

5. **Upgrading a stack built before the non-root change** — the app image now runs as uid
   `10001`, and an **existing** media volume is still owned by root, so photo uploads will
   fail with a permission error until it is handed over once:
   ```sh
   docker run --rm -v chorekeeper_media_data:/data/media alpine chown -R 10001:10001 /data/media
   ```
   A volume created after this change already has the right ownership — Docker seeds a new
   named volume from the image — so a fresh deployment needs nothing here.
6. **Cloudflare console (one-time):** steps 1–9 of
   [remote-access.md](remote-access.md) — tunnel hostname → `proxy:80`, Access apps A/B/C
   (including the `api/v1/checkin` **Bypass** — without it iOS Shortcuts get a Google
   redirect), cache-rule bypass for `/api/*`, WAF rate limit on `/api/v1/checkin/`.
   `docs/remote-access.md` §9b explains why the LAN door is safe; it is port `:81` inside
   the network and cloudflared has no route to it.
7. **Verify** with the checklist at the bottom of
   [remote-access.md](remote-access.md) (health 200, `/docs` 404, `/auth/me` 403,
   break-glass 404 through the tunnel, 401 on the host).

## Production readiness audit

A review before go-live. Everything below is either closed in the code, or listed as open
with what it would take.

### Closed

1. **Hardcoded dev credentials** (`chore`/`chore`, `dev-insecure-change-me`) and the DB
   secret repeated in three places — the prod file derives all of it from `${DB_PASSWORD:?}`
   and `${SESSION_SECRET:?}`, one source each, and the app now **refuses to start** under
   `ENVIRONMENT=prod` on the default session secret. It signs the media URLs as well as the
   session, so a prod stack running on the published default is handing out forgeable links
   while looking healthy.
2. **A known break-glass password on first boot.** The bootstrap seed planted
   `parent-dev-pass`, which is in this repo and which the LAN door will accept from any
   device on the wifi. It now requires `ADMIN_PASSWORD` and refuses without it (step 4).
3. **Restart policies were missing** on `db`/`api`/`worker`/`proxy` (only `cloudflared` had
   one). The prod file sets `restart: unless-stopped` everywhere — DockHand relies on
   Compose for this, the container runtime default is `no`.
4. **No healthchecks except the db one.** The prod file adds an API healthcheck
   (python-stdlib probe; `/health` is Access-exempt and loopback passes the Host
   allow-list). `worker`/`proxy`/`cloudflared` have no natural probe endpoint — they get
   restart policies; watch their logs.
5. **Worker/migration boot race** — the worker only waited for `api: started`, so it could
   touch tables before `alembic upgrade head` finished. Fixed: `api: service_healthy`.
6. **Floating image tags** (`postgres:17`, `cloudflared:latest`) — a redeploy could pull a
   new major, and a Postgres major upgrade does not start against an old data dir. Pinned
   in the prod file, and CI now runs the same Postgres pin; bump deliberately (Postgres
   upgrades: dump/restore).
7. **The overlay's `!override` tags needed Compose ≥2.24** — gone with the overlay; the
   single prod file uses nothing newer than Compose v2 basics.
8. **Containers ran as root.** The app image now runs as uid `10001` — it decodes
   attacker-supplied images, which is the one place hostile bytes meet a C library here.
   An existing media volume needs the one-time `chown` in step 5.
9. **Unbounded rate-limit state.** The limiter keyed a dict by the token in
   `/api/v1/checkin/{token}` — unauthenticated, Access-bypassed — so every value anyone
   sent was remembered for the life of the process. The maps are swept and capped, and that
   path now takes a per-IP limit as well: the per-token cap throttles use, not guessing.
10. **A stopped worker was invisible.** No chores generated, no misses detected, no money
    settled — and every screen still rendering. Each pass now stamps a heartbeat that
    `GET /admin/jobs` and the admin **Ops** screen report as stale after 5 minutes.
11. **Fresh-install noise.** An empty database is normal until step 4 runs, but the
    scheduler raised `NoResultFound` on it every tick — a traceback a minute, which is how
    a real fault gets missed. It logs one INFO line and does nothing.

### Open

1. **Backups never leave this machine.** `just backup` dumps the database and the media
   volume and `just restore-verify` proves a backup restores and reproduces every balance
   to the cent ([restore.md](restore.md)) — but it is local and manual, so a dead disk still
   loses everything. Point `CK_BACKUP_DIR` at a directory that is already replicated off-box,
   or add a timer; see the last section of restore.md.
2. **`ADMIN_EMAIL`, VAPID and the vision model default to empty** — web push stays off and
   photo scoring routes everything to `NEEDS_REVIEW` (fail-open, spec §6.3). Intended
   defaults, but know that an empty `LLM_VISION_MODEL` means the LLM is not scoring, not
   that it is broken.
3. **Vision LLM over plain http on the LAN** — photo bytes cross the home network
   unencrypted (same trust level as the LAN door; accepted). Prefer a LAN DNS name over a
   raw IP so a DHCP lease move does not silently disable scoring.
4. **Rate limits are per-process**, so an api restart forgives outstanding login backoff.
   Deliberate: one api replica serves every request, and the durable defences are Access,
   the WAF rule and the token entropy. Revisit if the api is ever scaled out.
