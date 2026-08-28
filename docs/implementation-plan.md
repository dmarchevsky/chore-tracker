# ChoreKeeper — Implementation Plan

## Status

- **Phase 0 — VLM bake-off:** not started
- **Phase 1 — Core skeleton:** ✅ done (baseline commit)
- **Phase 2 — Chores & scheduler:** not started
- **Phase 3 — Submissions & manual verification:** not started
- **Phase 4 — LLM verification:** not started
- **Phase 5 — Kid PWA:** not started
- **Phase 6 — Hardening & operations:** not started
- **Phase 7 — Nice-to-haves:** backlog

## Context

ChoreKeeper is a self-hosted chore tracker for a single household: a parent defines recurring
chores; kids submit photo/location/checkbox proof from a PWA inside a time window; a **local
vision LLM** scores photo proof against a natural-language rule; the parent reviews uncertain
cases; every pass/miss writes an append-only money ledger.

This plan turns [chore-tracker-spec.md](chore-tracker-spec.md) §14 into an executable,
phase-by-phase build. Each phase is independently demoable and gated by the spec's acceptance
criteria. Build order follows the spec exactly.

**Decided with the user:**
- Cover **all phases 0–7**.
- **Descoped:** external/remote access via Cloudflare Tunnel (§12.2 — `cloudflared` service,
  Cloudflare Access). The app is still built *as if* internet-reachable (strict CSP, HSTS,
  secure cookies, TOTP, rate limits) and Tailscale for the operator path is retained, but no
  tunnel service is composed or configured here. Adding it later is a compose-only change
  with no app code impact.
- Backend stack **exactly as spec'd**: Python 3.12, FastAPI + uvicorn, async SQLAlchemy 2.0 +
  Alembic, Postgres 17, Pydantic v2. Worker = same image, different entrypoint.
- Python tooling: **uv** for env/deps, **ruff** for lint+format, **pytest** for tests.

Day-to-day process (worktrees, feature branches, quality gates, push flow) is in
[../CLAUDE.md](../CLAUDE.md).

---

## Stack & conventions

| Concern | Choice |
|---|---|
| Language / runtime | Python 3.12, managed by `uv` (`uv.lock`, `pyproject.toml`) |
| Web | FastAPI, uvicorn (api), plain asyncio loop (worker) |
| DB / ORM | Postgres 17, SQLAlchemy 2.0 async (`asyncpg`), Alembic migrations |
| Validation | Pydantic v2 models for all request/response bodies |
| Auth | Local accounts, Argon2id (`argon2-cffi`), TOTP (`pyotp`), HTTP-only session cookie + CSRF token |
| Job queue | Postgres table + `SELECT ... FOR UPDATE SKIP LOCKED` (no Redis) |
| Image pipeline | Pillow (resize/orient/re-encode), `imagehash` or hand-rolled pHash, stdlib `hashlib` sha256 |
| LLM client | `httpx` async against OpenAI-compatible `/v1/chat/completions` |
| Frontend | React + TS + Vite, TanStack Query, Tailwind, `vite-plugin-pwa` |
| Lint/format | ruff (py), eslint + prettier (ts) |
| Tests | pytest + pytest-asyncio + httpx `AsyncClient` against a compose Postgres; Vitest + Playwright for the PWA in Phase 5 |
| Time | all `timestamptz` UTC in DB; wall-clock math in household TZ via `zoneinfo` |
| Money | integer cents, signed, never `UPDATE` a ledger row |

### Repo layout

```
backend/
  pyproject.toml  uv.lock
  alembic.ini  migrations/
  app/
    main.py                 # FastAPI app factory, router mounting, middleware
    config.py               # pydantic-settings, reads env (§13.2)
    db.py                   # async engine, session dependency
    models/                 # SQLAlchemy models, one module per aggregate
    schemas/                # Pydantic request/response models
    api/v1/                 # routers: auth, children, chores, occurrences, submissions,
                            #          verifications, payouts, checkin, push, health, admin_jobs
    services/               # domain logic: scheduling, rotation, cadence, ledger, verification,
                            #               anti_cheat, media, notifications
    auth/                   # password hashing, sessions, TOTP, CSRF, rate limiting, deps
    worker/
      __main__.py           # entrypoint: scheduler ticks + verification queue consumer
      scheduler.py  queue.py  verify.py
  tests/
frontend/
  package.json  vite.config.ts
  src/
    admin/  me/  shared/    # two shells behind one auth (§11)
    api/    hooks/    pwa/
docker-compose.yml   .env.example
justfile
scripts/vlm_bakeoff/       # Phase 0, standalone
eval/                      # labeled photo set + `just eval` harness
docs/
```

### Data model (tables — build incrementally, migration per phase)

`households`, `users` (role: admin|child; TOTP secret; argon2 hash), `sessions`,
`chores` (full field set from §4.1), `chore_occurrences`
(`unique(chore_id, due_at, assignee_id)`, status enum from §3 state machine,
`settlement_locked_at`, `was_late`), `submissions` (proof payload, client_meta, EXIF,
sha256, phash, `source` flag), `verifications` (kind llm|manual, verdict, confidence,
per-check answers JSON, raw request+response JSON), `ledger_entries` (append-only, signed
cents, `kind`, `occurrence_id` nullable, `reversed_by_entry_id`, partial unique index on
`(occurrence_id, kind) where kind in ('earning','penalty')`), `verification_jobs` (queue:
state, attempts, locked_at), `audit_log` (actor, ts, before/after JSON), `push_subscriptions`,
`notification_log`, `checkin_tokens` (per-kid, high-entropy, revocable).

### Binding decisions to honor (do not relitigate — cite the spec `[D]` in code comments)

- Chore **definition** vs materialized **occurrence** — all proof/money/history on the occurrence (§3).
- Occurrence state machine and its transition rules (§3); `MISSED` only ever set by the scheduler.
- Ledger append-only, integer cents, corrections = reversing entry (§9).
- Scheduler is **stateless reconciliation from the DB** — no in-memory timers anywhere (§8.3).
- Rotation math is the deterministic formula in §8.2.
- Anti-cheat flags **route to `NEEDS_REVIEW`, never auto-fail** (§6.1).
- LLM is an assistant: confidence **banding** not thresholding; **fail-open** to `NEEDS_REVIEW`
  on any infra error; `image_quality_issue != none` → leave `OPEN`, ask for retake (§6.3, §7.3).
- Media served only through authz'd API with 5-min signed URLs, stored outside web root (§5, §10).
- `TODO(decision)` comment + implement the **stated default** for every open `[Q]` (§15).

---

## Phase 0 — VLM bake-off  (`scripts/vlm_bakeoff/`, no app code)

**Goal:** choose a local vision model + prompt, or decide to launch in `llm_assist` mode.

- `scripts/vlm_bakeoff/run.py`: reads a labeled folder (`clean/`, `dirty/` for sink;
  `clean/`, `messy/` for room), sends each image through the §7.3 system+task prompt with the
  §7.3 JSON response schema, against a list of endpoints in a small YAML config.
- Report per model: precision/recall vs labels, mean + p95 latency, confidence calibration
  (reliability bins). Write `scripts/vlm_bakeoff/RESULTS.md`.
- Candidates to try (verify current llama.cpp mtmd support + mmproj first): Qwen-VL,
  Gemma vision, InternVL, MiniCPM-V. (Check whether the existing `llama-multi` server on
  host :8000 already serves a usable vision model.)
- Reuse the exact prompt strings here as the seed for `app/services/verification/prompts.py`
  later — keep them in one shared `prompts.py` from the start and import into the script.

**Accept when:** a model+prompt combo is chosen with documented precision/recall, or
`llm_assist` launch is decided; latency < 30 s/image on target hardware.

---

## Phase 1 — Core skeleton  ✅ done

Postgres schema + Alembic (migration `0001`: `households`, `users`, `sessions`, `audit_log`);
FastAPI app factory + security-headers middleware; local-account auth (Argon2id), server-side
sessions, CSRF double-submit, login rate limiting, TOTP enrol/verify for admins;
`/auth/*` + `/children` (child-account CRUD, password reset, soft deactivate) + `/health`;
worker heartbeat entrypoint; `docker-compose.yml` (`db`/`api`/`worker`); `justfile`;
`app/seed.py`; CI (ruff + `alembic upgrade head` + pytest).

**Accepted:** admin (with TOTP) + two child accounts log in; `just up && just seed && just test`
green from a clean clone (13 tests). API on host **:8088**.

---

## Phase 2 — Chores & scheduler

**Goal:** the four brief chores configurable via API; 14-day horizon generates correct
occurrences incl. biweekly rotation; idempotent; DST + month-boundary unit tests.

Work items:
1. Migration `0002`: `chores` (all §4.1 fields), `chore_occurrences`
   (`unique(chore_id, due_at, assignee_id)`, status enum, `was_late`, `settlement_locked_at`).
2. `app/services/cadence.py` — parse `daily|weekdays|weekends|weekly(on=[…])|monthly(day=N)|custom_rule`
   → list of local due datetimes in a range. Pure function, heavily unit-tested.
3. `app/services/rotation.py` — the exact §8.2 formula; `fixed|rotating|anyone|all` assignee
   resolution. `anyone` supported in the model, UI restricted to `fixed|rotating` (Q12 default).
4. `app/services/scheduler.py`:
   - `generate_occurrences(horizon_days=14)` — for each active chore, compute due datetimes in
     household TZ, resolve assignee, **upsert** on the unique key. Idempotent by construction.
   - `detect_missed()` — a query: `OPEN` rows where `now > due_at + grace` → `MISSED`. No timers.
   - `startup_reconcile()` — regenerate, requeue stuck jobs (>10 min `running`), log a summary.
5. `app/worker/scheduler.py` — run `generate_occurrences` hourly + on startup; `detect_missed`
   on a minute ticker. All "reconcile desired state from DB", asleep-safe.
6. `app/api/v1/chores.py` — `GET/POST /chores`, `GET/PATCH/DELETE /chores/{id}`
   (`PATCH ?apply=forward|future_generated`; DELETE = soft), `POST /chores/preview`
   (next N occurrences for an unsaved definition), `PATCH /occurrences/{id}/assignee` (swap + audit).
7. Tests: cadence for weekly/monthly edge cases; **DST transition day** ("before 8am" holds
   across the boundary); month-boundary (`monthly(day=31)` in Feb); rotation 4-week preview
   (`Alice, Alice, Bea, Bea`); running the generator twice → zero new rows.
8. Extend `app/seed.py` with the four example chores.

**Accept when:** all of the above verified by unit tests + a two-run generator check.

---

## Phase 3 — Submissions & manual verification

**Goal:** full loop end-to-end with `verification_mode: manual` — phone photo → admin inbox →
approve credits the exact amount **exactly once**; double-approve does not double-pay.

Work items:
1. Migration `0003`: `submissions`, `verifications`, `ledger_entries`
   (partial unique index on `(occurrence_id, kind) where kind in ('earning','penalty')`),
   payout rows via `ledger_entries` kind `payout`.
2. `app/services/media.py` — ingest pipeline (§7.1): read + record EXIF, normalize orientation,
   resize to 1568px long edge, re-encode JPEG q85, sha256 + pHash, write to
   `MEDIA_ROOT/{household}/{yyyy}/{mm}/{sha256[:2]}/{sha256}.jpg` (content-addressed = free dedup).
3. `app/services/ledger.py` — `credit_earning` / `debit_penalty` / `adjust` / `record_payout`,
   all as inserts; correction = reversing `adjustment` + set `reversed_by_entry_id`; balance =
   `SUM(amount_cents)`. Occurrence-transition + ledger-insert in **one transaction**.
4. `app/api/v1/occurrences.py` — `GET /occurrences?from&to&status&child` (self-scoped for kids),
   `GET /occurrences/{id}`, `POST /occurrences/{id}/submissions` (multipart: files[], note,
   geo, client_meta), `POST /occurrences/{id}/decision`
   (`approve|reject|excuse|redo`, `amount_override_cents?`, required `reason`),
   `POST /occurrences/{id}/dispute` (child).
5. `app/api/v1/submissions.py` — `GET /submissions/{id}/media/{n}`: HMAC-signed, 5-min TTL,
   authz on every request, never static. `app/api/v1/verifications.py` — `GET /verifications/{id}`.
6. `app/api/v1/payouts.py` — `POST /payouts` (writes negative `payout`, sets
   `settlement_locked_at` on covered occurrences), `GET /payouts`;
   `GET /children/{id}/balance`, `GET /children/{id}/ledger?from&to` (+ CSV export).
7. Minimal admin review UI: inbox list of `NEEDS_REVIEW|SUBMITTED|recent VERIFIED_FAIL`,
   per-occurrence detail (full-size photos, EXIF panel, timestamps, flags placeholder),
   Approve/Reject/Excuse/Redo/Adjust, bulk approve.
8. Extend seed: 30 days of backdated occurrences in mixed states (§13.3).
9. Tests: exactly-once earning under concurrent/double `decision`; `amount_override` +
   `late_multiplier`; signed-URL expiry + cross-session rejection; soft-delete keeps history.

**Accept when:** the manual loop works end to end; approve credits once; double approve does
not double-pay.

---

## Phase 4 — LLM verification

**Goal:** auto-pass and auto-fail both work end to end; killing the LLM container routes new
submissions to `NEEDS_REVIEW` with an error note and **zero** incorrect ledger entries.

Work items:
1. Migration `0004`: `verification_jobs` (state, attempts, `locked_at`).
2. `app/worker/queue.py` — claim jobs with `FOR UPDATE SKIP LOCKED`; retry policy; requeue
   rows `running` > 10 min on startup.
3. `app/services/anti_cheat.py` — pHash Hamming-distance search over last 120 days
   (`DUPLICATE_SUSPECTED`), EXIF `DateTimeOriginal` vs receive time > 15 min (`STALE_CAPTURE`),
   missing EXIF (`NO_EXIF`), screen-aspect + no camera make/model (`SCREENSHOT_SUSPECTED`),
   gallery-upload source (`GALLERY_UPLOAD`). Any flag → force `NEEDS_REVIEW`.
4. `app/services/verification/prompts.py` (shared with Phase 0) + `build_prompt(chore, photo)`
   from `verification_checklist` (fallback: single `verification_rule`).
5. `app/services/verification/llm.py` — `httpx` POST to `LLM_VISION_BASE_URL` with base64
   image(s), `response_format` json_schema (§7.2), `temperature 0.1`, `max_tokens 700`,
   `LLM_TIMEOUT_S`. Parse + validate; on failure **one** repair-prompt retry.
6. `app/services/verification/verdict.py` — verdict = all required checks pass; confidence =
   min of per-check confidences; `unclear` on a required check = fail but cap confidence 0.5;
   apply banding (`auto_pass_threshold` / `auto_fail_threshold`, defaults 0.85 / 0.35);
   `image_quality_issue != none` → leave `OPEN`, push "retake" message, **no** ledger entry;
   any anti-cheat flag → `NEEDS_REVIEW`; any infra error → `NEEDS_REVIEW` + `verification_error`.
7. `app/worker/verify.py` — the §7.1 step 1–7 pipeline; write `verification` row (full raw
   request + response), transition occurrence, ledger write only on terminal pass/fail, push.
8. Randomized prompt token (per-chore opt-in, default off): app shows a 2-digit number at
   capture; added as a required checklist item *"Is the number NN visible in this photo?"*.
9. `GET /health/llm` — VLM reachability. `just eval` — run the Phase 0 labeled set against the
   current prompt, report precision/recall per chore type.
10. `verification_mode` respected everywhere: `llm_auto`, `llm_assist` (LLM suggests → all to
    review), `manual`, `auto_accept` — switchable with **no code changes** (§7.2 fallback).
11. Tests: auto-pass + auto-fail happy paths; LLM down → `NEEDS_REVIEW`, no ledger row;
    resubmitted identical photo flagged; missing token fails token check on a token-enabled chore.

**Accept when:** all four acceptance scenarios above pass.

---

## Phase 5 — Kid PWA

**Goal:** installable and verified on **one iPhone + one Android**; full chore lock-screen →
verdict in < 60 s; airplane-mode submission uploads on reconnect; both check-in automations fire.

Work items:
1. Frontend scaffold: Vite + React + TS + Tailwind + TanStack Query + `vite-plugin-pwa`
   (installable, offline shell, Web Push). Vendor all fonts/JS locally — no CDN (§5).
2. Two shells behind one auth: `/admin/*` (tables, filters, review split-view) and `/me/*`
   (large touch targets, one primary action per screen, no nested nav). Test at 320px width.
3. Kid home = today's list + "due in X" + big capture buttons; then this week; then history.
4. `src/pwa/capture.tsx` — `getUserMedia` live viewfinder + shutter, frame → canvas → JPEG,
   client downscale to 1568px before upload; labeled capture slots from `photo_prompts`;
   camera-permission-denied recovery screen (not a dead end). File input only as the
   admin-enabled `allow_gallery_upload` escape hatch → flagged `GALLERY_UPLOAD`.
5. `src/pwa/offlineQueue.ts` — queue submission in IndexedDB on network drop, retry on reconnect.
6. Location check-in: `navigator.geolocation` with `enableHighAccuracy: true`; compute distance
   to geofence centroid; pass if `distance - accuracy <= radius`; `LOW_ACCURACY` (>100 m) →
   `NEEDS_REVIEW`; store coarse 4-dp point + boolean; 30-day retention.
7. `POST /api/v1/checkin/{kid_token}` webhook — token-scoped, unauthenticated, rate-limited
   20 req/h, can only move a `location` occurrence that is currently `OPEN`. Document +
   test the iOS Shortcuts and Android (Tasker / MacroDroid / HA companion) recipes; add a
   "last check-in seen" staleness warning to the admin dashboard.
8. Web Push (VAPID): `POST /push/subscribe`; kid events (window opening, T-30, verdict, redo);
   admin events (needs review, missed, dispute, 8:05 digest). Failed push never blocks the
   state machine; all sends logged. Onboarding flow walks each kid through Home-Screen install
   and detects/warns when running in a plain browser tab (iOS push needs the installed PWA).
9. Kid view **must not** show confidence numbers or anti-cheat flags — verdict + friendly
   message + redo button only. Kid sees own balance + statement, not the sibling's (Q1 default).
10. Kid read-only view of chore definitions — rules + amounts (Q8 default: yes).
11. Tests: Playwright happy path; offline-queue integration test; geofence math unit tests;
    manual device checklist doc for the iPhone + Android acceptance run.

**Accept when:** device-verified on one iPhone + one Android per the checklist.

---

## Phase 6 — Hardening & operations  (remote-access wiring descoped)

**Goal:** a restore from last night's backup into a clean env reproduces all balances exactly;
a security scan shows no unauthenticated endpoint other than `/health` and `/checkin/{token}`.

Work items:
1. Security headers / CSP: strict CSP (no external origins), HSTS, secure + `SameSite` cookies,
   no directory listing, no debug endpoints in prod — configured in `proxy` (caddy) + app
   middleware. **No `cloudflared` service, no Cloudflare Access** (descoped).
2. Retain the operator path: document Tailscale for SSH / Postgres / `llama-server` /
   `/admin/jobs`; `/api/admin/*` IP-restricted to the Tailscale CIDR when that path is used.
3. Rate limits across auth + `/checkin` + submission endpoints (Postgres-backed counters).
4. Retention jobs (worker cron-style ticks): photos → after `MEDIA_RETENTION_DAYS` (180)
   delete original, keep 256px thumbnail + verdict (Q2 default); geo points → 30 days.
5. Backup: nightly `pg_dump` + `MEDIA_ROOT` rsync to TrueNAS; `just backup` / `just restore`;
   **tested** restore procedure documented in `docs/restore.md`.
6. `GET /admin/jobs` dashboard — queue depth, failures, last tick; alert when the scheduler
   has not ticked (staleness check + push to admin).
7. Structured JSON logging with actor / timestamp / before-after on every admin override,
   ledger entry, and model call (§5 auditability).
8. Startup reconciliation flags occurrences that expired during a known outage window
   (admin bulk-excuse affordance).
9. Tests: backup→restore balance-equality integration test; an endpoint-inventory test that
   asserts every route requires auth except the two allowed.

**Accept when:** the two acceptance criteria above pass.

---

## Phase 7 — Nice-to-haves (backlog, not scheduled)

Streaks + bonus multipliers; sibling leaderboard (Q1); chore trading with parent approval;
weekly email/Push digest; "prompt token in photo" hardening; savings goals; recurring
auto-payout on Sundays. Keep as a backlog file `docs/backlog.md`; do not build in this pass.

---

## Open questions — implement the stated default + `TODO(decision)` (spec §15)

Q1 no cross-child visibility · Q2 180 d then thumbnail+verdict · Q3 allow negative balance ·
Q4 admin resets kid password · Q6 filesystem content-addressed media · Q7 assume ages 10–15 ·
Q8 kids get read-only chore definitions · Q9 dedicated Postgres container · Q10 digest except
school check-in (immediate) · Q11 manual payout, free-text method · Q12 `anyone` field exists,
UI only `fixed`/`rotating`. Q5/Q13/Q14 already resolved in-spec.

---

## Verification (end-to-end, per phase)

- **Every phase:** `just fmt && just lint && just test` green; `just up && just seed` yields a
  populated, non-empty UI.
- **Phase 0:** `python scripts/vlm_bakeoff/run.py` produces `RESULTS.md` with precision/recall +
  latency per model.
- **Phase 1:** from a clean clone, `just up && just seed && just test` green; log in as admin
  (with TOTP) and both kids via the API / a curl script.
- **Phase 2:** unit tests for cadence (DST day, month boundary), rotation 4-week preview;
  `POST /chores/preview` for each of the four brief chores; run the generator twice, assert
  row count unchanged; flip a machine clock forward and confirm `detect_missed` catches up.
- **Phase 3:** submit a photo via `POST /occurrences/{id}/submissions` from a phone on the LAN;
  it appears in the admin inbox; `POST /decision approve` credits the exact cents once;
  fire two approves concurrently, assert one ledger row; fetch a media URL, wait 6 min,
  assert 403.
- **Phase 4:** configure a chore `llm_auto`; submit a clean and a dirty photo, assert
  `VERIFIED_PASS` / `VERIFIED_FAIL` + correct ledger; `docker compose stop llm-vision`, submit,
  assert `NEEDS_REVIEW` + `verification_error` + no ledger row; resubmit the same file, assert
  `DUPLICATE_SUSPECTED`; enable a prompt token, submit without it, assert token check fails;
  `just eval` prints precision/recall.
- **Phase 5:** run the manual device checklist on one iPhone + one Android — install to home
  screen, capture, Web Push delivery, camera-permission recovery, airplane-mode submit →
  reconnect upload, and both geofence automations hitting `/checkin/{token}`.
- **Phase 6:** `just backup` then `just restore` into a fresh compose stack; diff every
  child balance — must be identical. Run an endpoint-inventory test / external scan; only
  `/health` and `/checkin/{token}` may be unauthenticated.
