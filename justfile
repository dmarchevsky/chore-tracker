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
eval:
    @echo "Phase 4: run eval/ harness against the Phase 0 labeled set"

backup:
    @echo "Phase 6: pg_dump + media rsync to TrueNAS"

restore:
    @echo "Phase 6: restore from last night's backup"
