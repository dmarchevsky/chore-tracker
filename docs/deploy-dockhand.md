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
   no users**, and nothing creates them automatically (verified: the worker scheduler logs
   `NoResultFound` every tick until a household exists). Bootstrap once from the host:
   ```sh
   docker compose -f docker-compose.prod.yml exec api python -m app.seed   # creates the household + the break-glass admin
   ```
   The seed gives the admin the dev password `parent-dev-pass` — **change it immediately**
   (Settings, over the LAN door) and bind the real Google address to the admin (the
   `ADMIN_EMAIL` migration only stamps emails of users that already exist, i.e. it matters
   when upgrading an existing dev database, not on a fresh install). Then add kids in the
   app + Access policy per [remote-access.md](remote-access.md) §5h.
5. **Cloudflare console (one-time):** steps 1–9 of
   [remote-access.md](remote-access.md) — tunnel hostname → `proxy:80`, Access apps A/B/C
   (including the `api/v1/checkin` **Bypass** — without it iOS Shortcuts get a Google
   redirect), cache-rule bypass for `/api/*`, WAF rate limit on `/api/v1/checkin/`.
   `docs/remote-access.md` §9b explains why the LAN door is safe; it is port `:81` inside
   the network and cloudflared has no route to it.
6. **Verify** with the checklist at the bottom of
   [remote-access.md](remote-access.md) (health 200, `/docs` 404, `/auth/me` 403,
   break-glass 404 through the tunnel, 401 on the host).

## Production readiness audit

Findings from preparing this bundle (fixed items are fixed *in the prod compose*; dev
files are left as they are):

1. **Backups — partly closed.** `just backup` dumps the database and the media volume, and
   `just restore-verify` proves a backup restores into a clean Postgres reproducing every
   balance to the cent. Full procedure: [restore.md](restore.md).
   **Still open:** the copies never leave this machine — `just backup` is local and manual,
   so a dead disk still loses everything. Point `CK_BACKUP_DIR` at a directory under `/home`
   (already rsynced to TrueNAS nightly) or add a timer; see the last section of restore.md.
2. **Hardcoded dev credentials** (`chore`/`chore`, `dev-insecure-change-me`) and the DB
   secret repeated in three places — fine locally, fixed in the prod file with
   `${DB_PASSWORD:?}`-derived config and a single source for each secret.
3. **Live secrets in the host `.env`** (session secret, tunnel token, Access AUDs).
   `.env` is gitignored and has never been committed — keep it that way. The tunnel token
   is a bearer credential: rotate it (Zero Trust → Refresh token) if the file ever leaks.
4. **Restart policies were missing** on `db`/`api`/`worker`/`proxy` (only `cloudflared` had
   one). The prod file sets `restart: unless-stopped` everywhere — DockHand relies on
   Compose for this, the container runtime default is `no`.
5. **No healthchecks except the db one.** The prod file adds an API healthcheck
   (python-stdlib probe; `/health` is Access-exempt and loopback passes the Host
   allow-list). `worker`/`proxy`/`cloudflared` have no natural probe endpoint — they get
   restart policies; watch their logs.
6. **Worker/migration boot race** — the worker only waited for `api: started`, so it could
   touch tables before `alembic upgrade head` finished. Fixed: `api: service_healthy`.
7. **Floating image tags** (`postgres:17`, `cloudflared:latest`) — a redeploy could pull a
   new major, and a Postgres major upgrade does not start against an old data dir. Pinned
   in the prod file; bump pins deliberately (Postgres upgrades: dump/restore).
8. **`ADMIN_EMAIL`, VAPID and the vision model default to empty** — web push stays off and
   photo scoring routes everything to `NEEDS_REVIEW` (fail-open, spec §6.3). Intended
   defaults, but know that an empty `LLM_VISION_MODEL` means the LLM is not scoring, not
   that it is broken.
9. **Vision LLM over a raw LAN IP + http** — a DHCP lease move silently disables scoring,
   and photo bytes cross the LAN unencrypted (same trust level as the LAN door; accepted).
   Prefer a LAN DNS name for `LLM_VISION_BASE_URL`.
10. **The overlay's `!override` tags needed Compose ≥2.24** — DockHand's agent version no
    longer matters; the single prod file uses nothing newer than Compose v2 spec basics.
11. **Fresh-install bootstrap is manual — open, medium** (found by smoke-booting this
    compose on an empty volume): nothing creates the first household/user — the
    `ADMIN_EMAIL` migration only stamps emails onto users that already exist — and until
    `python -m app.seed` runs, the worker logs `NoResultFound` every scheduler tick. The
    seed also hardcodes a known break-glass password (`parent-dev-pass`), so changing it
    must be step one after first sign-in. A code fix (create-the-household-on-first-run,
    quiet tick on empty DB, random first password) is app work beyond this bundle.
