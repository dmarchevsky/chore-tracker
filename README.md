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

## Remote access

`just tunnel-up` runs the Cloudflare Tunnel deployment (`docker-compose.tunnel.yml`) — one
outbound-only ingress, no open ports, and Cloudflare Access (Google) in front of the whole
app for parent and kids alike. SSH / Postgres / `llama-server` stay LAN-only; there is no
remote operator path. Full setup + the security tradeoffs:
[docs/remote-access.md](docs/remote-access.md).

## Status

**Phases 1–5 done; Phase 6 (hardening & operations) in progress.** See
[docs/implementation-plan.md](docs/implementation-plan.md) for what is built per phase.

## Quick start

Requires `docker` + `docker compose`, [`uv`](https://docs.astral.sh/uv/), and
[`just`](https://github.com/casey/just).

```sh
cp .env.example .env
just up          # build + start db, api, worker
just seed        # 1 household, admin "parent", children "alice"/"bea" (identities printed)
just test        # pytest against the compose Postgres (exposed on :5432)
```

API is on `http://localhost:8088` (host `:8000` is reserved for an existing llama-server).
Interactive docs at `/docs` when `ENVIRONMENT=dev`.

## Layout

- `backend/` — FastAPI + async SQLAlchemy 2.0, managed by `uv`. Worker shares the image
  (`python -m app.worker`).
- `backend/migrations/` — Alembic (async env).
- `frontend/Caddyfile` — the front door: serves the PWA, proxies `/api`, sets the strict
  security headers. Built into the `proxy` image.
- `docker-compose.yml` — `db`, `api`, `worker`; `proxy` behind a profile;
  `llm-vision` wired in Phase 4. `docker-compose.tunnel.yml` — Cloudflare Tunnel overlay.

## Auth notes

- **Sign-in is Google, via Cloudflare Access** (spec §12.1). Cloudflare authenticates the
  visitor at the edge; `GET /api/v1/auth/me` maps the verified `email` claim to a `users`
  row and mints the session, so there is no sign-in form. A parent adds a kid by entering
  their Google address under Kids — and in the Access policy, which is the half that
  actually lets them through the door.
- **Break-glass:** one local admin password (`POST /api/v1/auth/login`) for when Cloudflare
  or Google is unavailable. It is reachable only on the host's own port — the Caddy front
  door answers 404 for that path, so it never rides the tunnel. Set it from admin Settings.
- On the LAN stack (`just up`, no `CF_ACCESS_*`), break-glass is the only way in.
- Mutations require the `X-CSRF-Token` header echoing `csrf_token` from the login / `me`
  response. Session is an HTTP-only cookie (`ck_session`).
