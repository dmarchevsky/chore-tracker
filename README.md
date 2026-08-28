# ChoreKeeper

Self-hosted chore tracking with local-VLM proof verification. See
[docs/chore-tracker-spec.md](docs/chore-tracker-spec.md) for the full spec,
[docs/implementation-plan.md](docs/implementation-plan.md) for the phased build plan, and
[CLAUDE.md](CLAUDE.md) for the development workflow (worktrees, quality gates, push flow).

## Frontend

`frontend/` is the React + Vite + Tailwind PWA (kid `/me/*` + admin `/admin/*`).
`just web-dev` runs the Vite dev server (proxying `/api` to `:8088`); `just web-serve`
builds it and serves it behind nginx on `:5173`. Device acceptance:
[docs/device-checklist.md](docs/device-checklist.md).

## Status

**Phase 1 (core skeleton) — done.** Postgres schema + Alembic, FastAPI app, local-account
auth with TOTP for admins, child-account CRUD, Docker Compose, justfile, seed script, CI.

## Quick start

Requires `docker` + `docker compose`, [`uv`](https://docs.astral.sh/uv/), and
[`just`](https://github.com/casey/just).

```sh
cp .env.example .env
just up          # build + start db, api, worker
just seed        # 1 household, admin "parent", children "alice"/"bea" (creds printed)
just test        # pytest against the compose Postgres (exposed on :5432)
```

API is on `http://localhost:8088` (host `:8000` is reserved for an existing llama-server).
Interactive docs at `/docs` when `ENVIRONMENT=dev`.

## Layout

- `backend/` — FastAPI + async SQLAlchemy 2.0, managed by `uv`. Worker shares the image
  (`python -m app.worker`).
- `backend/migrations/` — Alembic (async env).
- `deploy/Caddyfile` — reverse proxy (fleshed out in Phase 6).
- `docker-compose.yml` — `db`, `api`, `worker`; `web`/`proxy` behind profiles;
  `llm-vision` wired in Phase 4.

## Auth notes

- Admin accounts require TOTP once enrolled. A freshly-seeded/created admin that has not
  enrolled may log in with a password alone **only** to reach `/api/v1/auth/totp/enroll`
  + `/confirm`; after that the code is mandatory.
- Mutations require the `X-CSRF-Token` header echoing `csrf_token` from the login / `me`
  response. Session is an HTTP-only cookie (`ck_session`).
