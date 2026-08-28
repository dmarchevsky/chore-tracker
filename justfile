# ChoreKeeper dev tasks (spec §13.3)
set dotenv-load := true

backend := "backend"
compose := "docker compose"

default:
    @just --list

# --- Container lifecycle -------------------------------------------------
up:
    {{compose}} up -d --build db api worker

down:
    {{compose}} down

logs service="":
    {{compose}} logs -f {{service}}

# --- Database ----------------------------------------------------------
db-up:
    {{compose}} up -d db

db-down:
    {{compose}} stop db

migrate:
    cd {{backend}} && uv run alembic upgrade head

makemigration message:
    cd {{backend}} && uv run alembic revision --autogenerate -m "{{message}}"

seed:
    {{compose}} exec -T api python -m app.seed

# --- Quality ---------------------------------------------------------
test *args:
    cd {{backend}} && uv run pytest {{args}}

fmt:
    cd {{backend}} && uv run ruff format . && uv run ruff check --fix .

lint:
    cd {{backend}} && uv run ruff check . && uv run ruff format --check .

# --- Later phases (placeholders) --------------------------------------
eval *args:
    cd {{backend}} && uv run python -m eval.run {{args}}

backup:
    @echo "Phase 6: pg_dump + media rsync to TrueNAS"

restore:
    @echo "Phase 6: restore from last night's backup"

# --- Frontend (PWA) --------------------------------------------------
web-install:
    cd frontend && npm ci

web-dev:
    cd frontend && npm run dev

web-build:
    cd frontend && npm run build

web-lint:
    cd frontend && npm run lint && npm run typecheck

web-test *args:
    cd frontend && npm run test {{args}}
