# CLAUDE.md — working agreement for ChoreKeeper

## Project

ChoreKeeper is a self-hosted, single-household chore tracker: a parent defines recurring
chores; kids submit photo / location / checkbox proof from a PWA inside a time window; a
**local vision LLM** scores photo proof; the parent reviews uncertain cases; every pass or
miss writes an append-only money ledger. Photos, prompts and locations are scored and stored
at home and never sent to a model provider; the Cloudflare edge terminates TLS in front of
the app, and Google + Cloudflare hold sign-in identity but never chore content (spec §12).

- **Source of truth:** [docs/chore-tracker-spec.md](docs/chore-tracker-spec.md) — the spec.
  `[D]` = settled decision (don't relitigate), `[Q]` = open question (implement the stated
  default, leave a `TODO(decision)` comment).
- **Quick start:** [README.md](README.md).

## Stack & layout

Python 3.12 · FastAPI + uvicorn · async SQLAlchemy 2.0 (`asyncpg`) · Alembic · Postgres 17 ·
Pydantic v2. Managed by **uv**. Lint/format **ruff**, tests **pytest**.

- `backend/app/` — API (`main.py` factory, `api/v1/` routers, `services/` domain logic,
  `auth/`, `models/`, `schemas/`).
- `backend/app/worker/` — scheduler ticks + verification queue (same image, entrypoint
  `python -m app.worker`).
- `backend/migrations/` — Alembic (async `env.py`), one migration per phase.
- **Two compose files, two modes, no overlay between them** — `docker-compose.yml` is dev
  (`db` `api` `worker` `proxy`; LAN only; `DEV_AUTH` passwordless sign-in; no tunnel, no
  break-glass) and `docker-compose.prod.yml` is production (adds `cloudflared`, Cloudflare
  Access, break-glass on the LAN door). Separate compose projects — `chorekeeper` and
  `chorekeeper-prod` — with separate volumes, so `just up` cannot disturb the live household
  stack. They do both bind `:5173` and `:8088`: **stop one before starting the other.**
  **API on host `:8088`** — host `:8000` is a pre-existing llama-server, do not use it.

## Dev commands (see [justfile](justfile))

Prerequisites: `docker` + `docker compose`, `uv`, and [`just`](https://github.com/casey/just)
(`dnf install just` / `cargo install just`). Without `just`, run the recipe body directly
(e.g. `cd backend && uv run pytest`).

| Task | Command |
|---|---|
| Postgres only (for tests) | `just db-up` / `just db-down` |
| Full dev stack | `just up` (released ghcr images, pulled once) / `just up-build` (builds the working tree) / `just down` |
| Back to the released dev images | `just pull` (after a local build re-tagged them) |
| Production stack | `just prod-up` / `just prod-pull` / `just prod-down` / `just prod-ps` (needs `env.production`, incl. `CHOREKEEPER_VERSION`) |
| **Release** | `just release X.Y.Z` — tags + pushes `vX.Y.Z`; **ask first** (see "Release — ask first") |
| Migrations | `just migrate` · `just makemigration "message"` |
| VAPID keys for web push | `just vapid-keys` (prints a pair; writes nothing — [docs/notifications.md](docs/notifications.md)) |
| Seed dev data | `just seed` — **ASK FIRST, every time** (see below). Needs `ADMIN_PASSWORD` set when `ENVIRONMENT=prod`; it refuses otherwise |
| **Lint gate (backend)** | `just lint` (ruff check + `ruff format --check`) |
| Autofix | `just fmt` |
| **Test gate (backend)** | `just test` (pytest; needs Postgres reachable on `:5432`) |
| Drop stale test databases | `just test-db-prune` (after removing worktrees) |
| PWA deps | `just web-install` (once per worktree — `node_modules` is not shared) |
| **Lint gate (PWA)** | `just web-lint` (eslint + `prettier --check` + `tsc --noEmit`) |
| **Test gate (PWA)** | `just web-test` (vitest) |
| **Rebuild + serve the PWA** | `just web-serve` (rebuilds the `proxy` image, serves on `:5173`) |
| Backup | `just backup [prod\|dev]` · `just backup-list` ([docs/restore.md](docs/restore.md)) |
| **Verify a backup** | `just restore-verify <dir>` (throwaway Postgres, balances compared — safe) |
| Restore over a stack | `just restore <dir> <stack> overwrite-production` — **destructive, ask first** |

### Seeding and wiping data — ASK FIRST, EVERY TIME

**Never run `just seed` without the user's explicit approval for that specific run.** The same
goes for anything that destroys or replaces data: `docker volume rm`, `docker compose down -v`,
`DROP`/`TRUNCATE`/`DELETE` against any database, or restoring a dump over an existing one.
Blanket permission is never implied — not by "set up dev", not by an empty-looking database,
and not by approval given for an earlier run.

Ask with the specifics: which database, which volume by name, and what is in it right now
(row counts of `users` / `chores` / `chore_occurrences` / `ledger_entries`). Then wait.

`just restore` already does exactly this before it will touch anything — it refuses without
`overwrite-production` and prints the counts first. Take a `just backup` before any of it.

**Why:** the dev and prod stacks are one letter apart in the volume name, the ledger is
append-only by design (spec §9), and a seeded household looks exactly like a real one from
the terminal. There is no undo — `chorekeeper_db_data` holds the family's real chores and
money, and the only reason a wipe has been safe so far is that it happened to hit
`chorekeeper_dev_db_data` instead.

`just test` gives each checkout its own test database, named after its directory, so two
worktrees can run the gate at the same time without truncating each other's tables — a shared
one produced dozens of failures that were pure noise. `just test-db-prune` drops them.

`just up` runs the **released** images (`CHOREKEEPER_VERSION`, default `latest`) and builds
nothing; `just up-build` builds `api` `worker` `proxy` from the checkout — see step 9. Sign
in to the dev stack at `http://localhost:5173` by picking a user; there is no password and
no Google.

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
   - touched `frontend/`? `just web-install` (each worktree has its own `node_modules`),
     then `just web-lint` and `just web-test` → both green
   - models changed? `just makemigration "..."`, eyeball the autogenerate diff,
     `just migrate` applies with no error
   - **`CHANGELOG.md`:** one line under `## [Unreleased]` (Added / Changed / Fixed) saying
     what changed for a household or an operator — part of the same single commit. Pure
     refactors, tests and docs typos can skip it.
5. **Commit once:**
   ```
   <phase-tag>: <imperative summary>

   <what & why; cite spec §section / [D] where relevant>
   ```
   e.g. `phase2: add cadence parser for daily/weekly/monthly rules`.
6. **Rebase onto `main`, re-verify:** in the worktree `git rebase main`, resolve, then
   re-run `just lint && just test`.
7. **Fast-forward merge:** `git switch main && git merge --ff-only feat/<slug>`
   (`--ff-only` fails loudly if step 6 was skipped — intended).
8. **Clean up worktrees BEFORE Docker:**
   `git worktree remove .worktrees/feat-<slug>` · `git branch -d feat/<slug>` ·
   `git worktree prune`. `git worktree list` must show only the main checkout.
9. **Green build = Docker up and healthy.** This runs the **dev** stack, on its own compose
   project and its own volumes; if the production stack is running, `just prod-down` first
   (both bind `:5173` and `:8088`) and `just prod-up` again when you are done. From `main`:
   **`just up-build`** — not `just up`, which runs the last *release* and would prove
   nothing about this commit — then verify
   - `docker compose ps` → `db` healthy, `api` + `worker` up
   - `curl -sf localhost:8088/api/v1/health` → `{"status":"ok"}`
   - `docker compose logs worker` → tick loop, no tracebacks

   `just up-build` builds `proxy` too, so the bundle is fresh. When the branch touched
   `frontend/`, still check it is the one being served:
   - `just web-serve` → rebuilds just the `proxy` image (for later PWA-only iterations)
   - `docker compose ps proxy` → up, and `curl -sf localhost:5173/` → 200
   - confirm the new bundle is actually being served, e.g.
     `curl -s localhost:5173/ | grep -o '/assets/index-[^"]*\.js'` then grep that asset
     for a string only the new code contains
   - in the browser, hard-reload (Ctrl+Shift+R) — it is an installed PWA with a service
     worker, so a normal reload can still hand you the cached bundle
10. **Push only after the user confirms.** Report commits ahead of `origin/main`, gates
    passed, stack healthy; ask. On explicit "yes": `git push origin main`. CI
    ([.github/workflows/ci.yml](.github/workflows/ci.yml): ruff + `alembic upgrade head` +
    pytest) is the remote safety net, not a replacement for the local gates.

## Release — ask first

A release is a `vX.Y.Z` tag on `main`. The tag is what publishes: the Release workflow
([.github/workflows/release.yml](.github/workflows/release.yml)) reruns the CI gates, requires
a `## [X.Y.Z]` section in `CHANGELOG.md`, pushes `ghcr.io/dmarchevsky/chorekeeper-api` and
`chorekeeper-proxy`, and opens a GitHub Release from that section. Production then runs it
when its `CHOREKEEPER_VERSION` is set to it ([docs/deploy-dockhand.md](docs/deploy-dockhand.md#releases)).
A pushed tag cannot be quietly taken back — images get pulled — so **every step that leaves
this machine needs the user's yes for that run.**

1. **Only when the user asks for a release.** Read `## [Unreleased]`, propose the version —
   patch for fixes only, minor for anything added, major for anything a household or operator
   must act on (a required env var, a breaking API, a migration that cannot be rolled back) —
   and wait for a yes. Not `0.0.x`; the first release is `0.1.0`.
2. **Release commit, through the normal workflow** (worktree `feat/release-X.Y.Z`, steps 1–8):
   in `CHANGELOG.md` rename `## [Unreleased]` to `## [X.Y.Z] - <today, YYYY-MM-DD>`, put a
   fresh empty `## [Unreleased]` above it, and update the link references at the bottom
   (`[Unreleased]: …/compare/vX.Y.Z...main`, `[X.Y.Z]: …/compare/v<prev>...vX.Y.Z`, or
   `…/releases/tag/vX.Y.Z` for the first). Nothing else in that commit. Message:
   `release: X.Y.Z`. Fast-forward, then push `main` only on a yes (step 10).
3. **Tag:** `just release X.Y.Z` — ask first; it pushes. It refuses off `main`, on a dirty or
   unpushed tree, on an existing tag, or without the section. Then `gh run watch` the Release
   run until green and confirm both images exist:
   `docker manifest inspect ghcr.io/dmarchevsky/chorekeeper-api:X.Y.Z` (and `-proxy`).
   A red run publishes nothing; fix forward with `X.Y.(Z+1)` — never move or reuse a tag.
4. **Deploy only on request.** The user sets `CHOREKEEPER_VERSION=X.Y.Z` in the Dockhand
   stack environment (`chore-tracker-prod` on `debian2`) — the `dockhand-deploy` script
   cannot edit it. Then plan, confirm, deploy and verify through that skill. Roll back the
   same way with the previous version.

**Never:** push without explicit confirmation · tag, release or deploy without explicit
per-run confirmation · move, delete or reuse a release tag · **seed, wipe a volume, or drop/restore a
database without explicit per-run approval** · commit on `main` directly · merge with a
failing gate or an un-rebased branch · bypass `--ff-only` · run `just up` / `just up-build`
with worktrees still present.

## Code conventions

- Money: integer **cents**, signed; ledger is **append-only** — corrections are reversing
  entries, never `UPDATE` (spec §9).
- Time: store `timestamptz` in **UTC**; do wall-clock/cadence math in the household timezone
  via `zoneinfo` (spec §8.4).
- Scheduler: **stateless reconciliation from the DB** — no in-memory timers (spec §8.3).
- Anti-cheat flags route to `NEEDS_REVIEW`, never auto-fail (spec §6.1). LLM is an assistant:
  confidence banding, fail-open to `NEEDS_REVIEW` on infra error (spec §6.3).
- Match surrounding style; keep comment density and naming consistent with the module.
