# CLAUDE.md — working agreement for ChoreKeeper

## Project

ChoreKeeper is a self-hosted, single-household chore tracker: a parent defines recurring
chores; kids submit photo / location / checkbox proof from a PWA inside a time window; a
**local vision LLM** scores photo proof; the parent reviews uncertain cases; every pass or
miss writes an append-only money ledger. Nothing (photos, prompts, locations) leaves the LAN.

- **Source of truth:** [docs/chore-tracker-spec.md](docs/chore-tracker-spec.md) — the spec.
  `[D]` = settled decision (don't relitigate), `[Q]` = open question (implement the stated
  default, leave a `TODO(decision)` comment).
- **Phased roadmap:** [docs/implementation-plan.md](docs/implementation-plan.md).
- **Quick start:** [README.md](README.md).

## Stack & layout

Python 3.12 · FastAPI + uvicorn · async SQLAlchemy 2.0 (`asyncpg`) · Alembic · Postgres 17 ·
Pydantic v2. Managed by **uv**. Lint/format **ruff**, tests **pytest**.

- `backend/app/` — API (`main.py` factory, `api/v1/` routers, `services/` domain logic,
  `auth/`, `models/`, `schemas/`).
- `backend/app/worker/` — scheduler ticks + verification queue (same image, entrypoint
  `python -m app.worker`).
- `backend/migrations/` — Alembic (async `env.py`), one migration per phase.
- `docker-compose.yml` — services `db` / `api` / `worker` (`web` / `proxy` behind profiles;
  `llm-vision` wired in Phase 4). **API on host `:8088`** — host `:8000` is a pre-existing
  llama-server, do not use it.

## Dev commands (see [justfile](justfile))

Prerequisites: `docker` + `docker compose`, `uv`, and [`just`](https://github.com/casey/just)
(`dnf install just` / `cargo install just`). Without `just`, run the recipe body directly
(e.g. `cd backend && uv run pytest`).

| Task | Command |
|---|---|
| Postgres only (for tests) | `just db-up` / `just db-down` |
| Full app stack | `just up` (builds + starts `db` `api` `worker`) / `just down` |
| Migrations | `just migrate` · `just makemigration "message"` |
| Seed dev data | `just seed` |
| **Lint gate** | `just lint` (ruff check + `ruff format --check`) |
| Autofix | `just fmt` |
| **Test gate** | `just test` (pytest; needs Postgres reachable on `:5432`) |

## Git workflow — MUST follow for every change

**One feature = one branch = one worktree = one commit.** Never commit straight to `main`.
History on `main` is **linear** (rebase + fast-forward, no merge commits).

1. **Clean, current `main`.** `git switch main`, working tree clean.
2. **Branch + worktree:**
   `git worktree add .worktrees/feat-<slug> -b feat/<slug>` then `cd .worktrees/feat-<slug>`.
   Slug names one logical feature, e.g. `feat/phase2-cadence-parser`.
3. **Implement only that feature.** Include tests for new/changed behavior on the same branch.
4. **Quality gates — all green in the worktree before committing:**
   - `just db-up` (once per machine session) so the test DB is up
   - `just fmt` then `just lint` → clean
   - `just test` → green, and the new behavior is actually covered
   - models changed? `just makemigration "..."`, eyeball the autogenerate diff,
     `just migrate` applies with no error
5. **Commit once:**
   ```
   <phase-tag>: <imperative summary>

   <what & why; cite spec §section / [D] where relevant>

   Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
   ```
   e.g. `phase2: add cadence parser for daily/weekly/monthly rules`.
6. **Rebase onto `main`, re-verify:** in the worktree `git rebase main`, resolve, then
   re-run `just lint && just test`.
7. **Fast-forward merge:** `git switch main && git merge --ff-only feat/<slug>`
   (`--ff-only` fails loudly if step 6 was skipped — intended).
8. **Clean up worktrees BEFORE Docker:**
   `git worktree remove .worktrees/feat-<slug>` · `git branch -d feat/<slug>` ·
   `git worktree prune`. `git worktree list` must show only the main checkout.
9. **Green build = Docker up and healthy.** From `main`: `just up`, then verify
   - `docker compose ps` → `db` healthy, `api` + `worker` up
   - `curl -sf localhost:8088/api/v1/health` → `{"status":"ok"}`
   - `docker compose logs worker` → tick loop, no tracebacks
10. **Push only after the user confirms.** Report commits ahead of `origin/main`, gates
    passed, stack healthy; ask. On explicit "yes": `git push origin main`. CI
    ([.github/workflows/ci.yml](.github/workflows/ci.yml): ruff + `alembic upgrade head` +
    pytest) is the remote safety net, not a replacement for the local gates.

**Never:** push without explicit confirmation · commit on `main` directly · merge with a
failing gate or an un-rebased branch · bypass `--ff-only` · run `just up` with worktrees
still present.

## Code conventions

- Money: integer **cents**, signed; ledger is **append-only** — corrections are reversing
  entries, never `UPDATE` (spec §9).
- Time: store `timestamptz` in **UTC**; do wall-clock/cadence math in the household timezone
  via `zoneinfo` (spec §8.4).
- Scheduler: **stateless reconciliation from the DB** — no in-memory timers (spec §8.3).
- Anti-cheat flags route to `NEEDS_REVIEW`, never auto-fail (spec §6.1). LLM is an assistant:
  confidence banding, fail-open to `NEEDS_REVIEW` on infra error (spec §6.3).
- Match surrounding style; keep comment density and naming consistent with the module.
