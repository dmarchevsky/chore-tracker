# ChoreKeeper

Self-hosted chore tracking with local-VLM proof verification. See
[docs/chore-tracker-spec.md](docs/chore-tracker-spec.md) for the full spec,
[docs/implementation-plan.md](docs/implementation-plan.md) for the phased build plan, and
[CLAUDE.md](CLAUDE.md) for the development workflow (worktrees, quality gates, push flow).

## Frontend

`frontend/` is the React + Vite + Tailwind PWA (kid `/me/*` + admin `/admin/*`).
`just web-dev` runs the Vite dev server (proxying `/api` to `:8088`); `just web-serve`
builds it and serves it behind Caddy on `:5173`. Device acceptance:
[docs/device-checklist.md](docs/device-checklist.md).

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
— but both bind `:5173` and `:8088`, so stop one before starting the other.

**Remote access:** one outbound-only ingress, no open ports, Access (Google) in front of the
whole app for parent and kids alike. SSH / Postgres / `llama-server` stay LAN-only; there is
no remote operator path. Full setup + the security tradeoffs:
[docs/remote-access.md](docs/remote-access.md). Deploying the prod file under an
orchestrator, plus the readiness audit: [docs/deploy-dockhand.md](docs/deploy-dockhand.md).

## Backups

`just backup` writes the database, the media volume and a manifest of row counts and per-child
balances to `backups/`. `just restore-verify <dir>` proves a backup restores into a clean
Postgres reproducing every balance to the cent — an untested backup is a rumour. Backups are
currently local and manual: [docs/restore.md](docs/restore.md).

## Status

**Phases 1–5 done; Phase 6 (hardening & operations) in progress.** See
[docs/implementation-plan.md](docs/implementation-plan.md) for what is built per phase.

## Quick start

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

## Layout

- `backend/` — FastAPI + async SQLAlchemy 2.0, managed by `uv`. Worker shares the image
  (`python -m app.worker`).
- `backend/migrations/` — Alembic (async env).
- `frontend/Caddyfile` — the front door: serves the PWA, proxies `/api`, sets the strict
  security headers. Built into the `proxy` image.
- `docker-compose.yml` — the dev stack: `db`, `api`, `worker`, `proxy`.
  `docker-compose.prod.yml` — the production stack, tunnel and all, in one file.

## Auth notes

- **Sign-in is Google, via Cloudflare Access** (spec §12.1). Cloudflare authenticates the
  visitor at the edge; `GET /api/v1/auth/me` maps the verified `email` claim to a `users`
  row and mints the session, so there is no sign-in form. A parent adds a kid by entering
  their Google address under Kids — and in the Access policy, which is the half that
  actually lets them through the door.
- **Break-glass:** one local admin password (`POST /api/v1/auth/login`) for when Cloudflare
  or Google is unavailable. On a fresh production database the bootstrap seed takes it from
  `ADMIN_PASSWORD` and refuses to run without one. In the tunnel deployment it lives on a **LAN door** —
  `http://<home-ip>:5173`, a second Caddy site the tunnel has no route to — while the public
  hostname answers 404 for that path. Set the password from admin Settings.
- **Dev sign-in:** the dev stack sets `DEV_AUTH`, which adds `/auth/dev/users` +
  `/auth/dev/login` — the login page lists the household and you click a name. Those routes
  404 in every other configuration, break-glass 404s while `DEV_AUTH` is on, and the API
  refuses to start with `DEV_AUTH` under `ENVIRONMENT=prod` or alongside `CF_ACCESS_*`.
- Mutations require the `X-CSRF-Token` header echoing `csrf_token` from the login / `me`
  response. Session is an HTTP-only cookie (`ck_session`).
