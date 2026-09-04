# ChoreKeeper tasks (spec §13.3)
#
# Two modes, two compose files, no overlay between them:
#   dev   docker-compose.yml       `just up`      LAN only, passwordless picker sign-in
#   prod  docker-compose.prod.yml  `just prod-up` Cloudflare Tunnel + Google via Access
#
# They are separate compose PROJECTS (chorekeeper / chorekeeper-prod) with separate
# volumes, so `just up` can never disturb the household's live stack — but they do both
# bind :5173 and :8088, so stop one before starting the other.
#
# Each checkout gets its own test database, named after its directory (see
# backend/tests/conftest.py) — the suite rebuilds the schema and truncates every table, so a
# shared one meant two worktrees running `just test` at once destroyed each other's data and
# reported failures that were pure noise. `just test-db-prune` drops them when worktrees go.
#
# No `set dotenv-load` on purpose: it exported the repo's .env into every recipe, so a
# recipe run inside .worktrees/<branch> silently picked up the MAIN checkout's .env —
# `just test` in particular. The dev compose file pins its own values as literals and the
# prod recipes pass --env-file explicitly, so nothing needs it.

backend := "backend"
compose := "docker compose"
prod := compose + " -f docker-compose.prod.yml --env-file env.production"

default:
    @just --list

# --- Dev stack (docker-compose.yml) --------------------------------------

# Build and start the whole dev stack; sign in at http://localhost:5173, no password
up:
    {{compose}} up -d --build

# Stop the dev stack
down:
    {{compose}} down

# Follow dev logs, optionally for one service
logs service="":
    {{compose}} logs -f {{service}}

# --- Production stack (docker-compose.prod.yml + env.production) ---------

# Build and start production — tunnel + Access. Stop the dev stack first
prod-up:
    {{prod}} up -d --build

# Stop the production stack
prod-down:
    {{prod}} down

# Follow production logs, optionally for one service
prod-logs service="":
    {{prod}} logs -f {{service}}

# What production is running right now
prod-ps:
    {{prod}} ps

# --- Database ------------------------------------------------------------

# Postgres alone — what `just test` needs
db-up:
    {{compose}} up -d db

# Stop Postgres
db-down:
    {{compose}} stop db

# Drop every per-worktree test database — run after `git worktree remove`
test-db-prune:
    @{{compose}} exec -T db psql -U chore -d postgres -tAc \
        "SELECT datname FROM pg_database WHERE datname LIKE 'chore\_test%'" \
      | tee /dev/stderr \
      | xargs -r -I{} {{compose}} exec -T db psql -U chore -d postgres -q \
        -c 'DROP DATABASE IF EXISTS "{}" WITH (FORCE)'

# Apply migrations to the database in DATABASE_URL
migrate:
    cd {{backend}} && uv run alembic upgrade head

# Autogenerate a migration from the models
makemigration message:
    cd {{backend}} && uv run alembic revision --autogenerate -m "{{message}}"

# Print a fresh VAPID keypair for web push — paste into .env (docs/notifications.md)
vapid-keys:
    cd {{backend}} && uv run python -m app.vapid_keys

# Redraw the app icons into frontend/public (uses the backend's Pillow)
icons:
    cd {{backend}} && uv run python ../scripts/icons.py ../frontend/public

# Fill the dev database with a household, chores and backdated occurrences
seed:
    {{compose}} exec -T api python -m app.seed

# --- Quality gates -------------------------------------------------------

# Backend tests (needs Postgres on :5432)
test *args:
    cd {{backend}} && uv run pytest {{args}}

# Autofix backend formatting and lints
fmt:
    cd {{backend}} && uv run ruff format . && uv run ruff check --fix .

# Backend lint gate
lint:
    cd {{backend}} && uv run ruff check . && uv run ruff format --check .

# Score the vision model against the labelled set (spec §7)
eval *args:
    cd {{backend}} && uv run python -m eval.run {{args}}

# --- Frontend (PWA) ------------------------------------------------------

# Install node_modules — once per worktree, they are not shared
web-install:
    cd frontend && npm ci

# Vite dev server with /api proxied to :8088
web-dev:
    cd frontend && npm run dev

# Build the production bundle
web-build:
    cd frontend && npm run build

# PWA lint gate: eslint + prettier + tsc
web-lint:
    cd frontend && npm run lint && npm run typecheck

# PWA test gate: vitest
web-test *args:
    cd frontend && npm run test {{args}}

# Rebuild the bundle into the proxy image — `just up` does NOT do this
web-serve:
    {{compose}} up -d --build proxy

# --- Backup & restore (docs/restore.md) ----------------------------------

# Back up a stack (default prod) to backups/ — database, media and a checked manifest
backup stack="prod":
    ./scripts/backup.sh {{stack}}

# List the backups taken so far, newest last
backup-list:
    @ls -1dt {{env_var_or_default("CK_BACKUP_DIR", "backups")}}/chorekeeper-* 2>/dev/null | tac || echo "no backups yet — run: just backup"

# Prove a backup restores: throwaway Postgres, every balance compared. Touches nothing.
restore-verify dir:
    ./scripts/restore.sh verify {{dir}}

# DESTRUCTIVE: replace a stack's data with a backup. Needs confirm=overwrite-production
restore dir stack="prod" confirm="":
    ./scripts/restore.sh apply {{dir}} {{stack}} {{confirm}}
