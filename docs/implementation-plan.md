# ChoreKeeper — Implementation Plan

## Status

- **Phase 0 — VLM bake-off:** not started
- **Phase 1 — Core skeleton:** ✅ done (baseline commit)
- **Phase 2 — Chores & scheduler:** ✅ done
- **Phase 3 — Submissions & manual verification:** ✅ done
- **Phase 4 — LLM verification:** ✅ done
- **Phase 5 — Kid PWA:** ✅ built (device sign-off pending — see docs/device-checklist.md)
- **Phase 6 — Hardening & operations:** in progress (Access/tunnel, retention, LLM config landed)
- **Phase 7 — Nice-to-haves:** backlog

Shipped after the numbered phases above, each in its own migration and not planned here:
disputes (`phase7_disputes`), missed-chore settlement (`phase8_missed_settlement`), and
manual penalties (`phase9_manual_penalties`, below).

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
- ~~**Descoped:** external/remote access via Cloudflare Tunnel~~ — **wired** (§12.2):
  `cloudflared` + a single Caddy front door in `docker-compose.prod.yml`, Cloudflare
  Access (Google) in front of the whole hostname, plus the app hardening the LAN-only
  assumptions needed (proxy-aware client IP, `TrustedHost`, `Secure` cookies in prod,
  `Cf-Access-Jwt-Assertion` verification). Setup + tradeoffs in
  [remote-access.md](remote-access.md). The operator path is LAN/physical only — no Tailscale.
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
| Auth | Google via Cloudflare Access (`pyjwt`), HTTP-only session cookie + CSRF token; Argon2id (`argon2-cffi`) for the break-glass admin password only |
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
    auth/                   # Cloudflare Access verification, sessions, CSRF, rate limiting, deps
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

`households`, `users` (role: admin|child; Google email; argon2 hash for break-glass only), `sessions`,
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
sessions, CSRF double-submit, login rate limiting, TOTP enrol/verify for admins
(**superseded in Phase 6** — see §12.1: identity is Google via Cloudflare Access, and password
+ TOTP are gone bar one break-glass admin password);
`/auth/*` + `/children` (child-account CRUD, soft deactivate) + `/health`;
worker heartbeat entrypoint; `docker-compose.yml` (`db`/`api`/`worker`); `justfile`;
`app/seed.py`; CI (ruff + `alembic upgrade head` + pytest).

**Accepted:** admin + two child accounts log in; `just up && just seed && just test`
green from a clean clone (13 tests). API on host **:8088**.

---

## Phase 2 — Chores & scheduler  ✅ done

**Goal:** the four brief chores configurable via API; 14-day horizon generates correct
occurrences incl. biweekly rotation; idempotent; DST + month-boundary unit tests.

**Accepted:** migration `0002` (`chores`, `chore_occurrences`); `cadence.py` +
`rotation.py` (DST-safe, monthly clamp, biweekly = Alice/Alice/Bea/Bea);
`scheduler.py` stateless reconcile (generate / open_due_windows / detect_missed) wired
into the worker loop; chores CRUD + `/chores/preview` + `/occurrences` list +
`/occurrences/{id}/assignee` swap with audit; seed grows the four brief chores.
`just test` green (69 tests). Shipped over 4 feature branches.

Original work items (for reference):
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

## Phase 3 — Submissions & manual verification  ✅ done

**Goal:** full loop end-to-end with `verification_mode: manual` — phone photo → admin inbox →
approve credits the exact amount **exactly once**; double-approve does not double-pay.

**Accepted:** migration `0003` (`submissions` + `submission_media`, `verifications`,
`ledger_entries` with the partial exactly-once index); `media.py` ingest pipeline
(EXIF, orient, 1568px, JPEG q85, sha256 + dHash, content-addressed) + HMAC-signed
5-minute media URLs served only through the authz'd API; `ledger.py`
(credit/debit/reverse/adjust/payout, exactly-once, late multiplier, settlement lock);
`review.py` state-machine orchestration for `POST /occurrences/{id}/submissions`,
`/decision`, `/dispute` + `?inbox=true`; `geo.py` check-in math; `/payouts` +
`/children/{id}/balance` `/ledger` `/ledger.csv`; seed grows 30 days of mixed-state
occurrences. `just test` green (98 tests). Shipped over 6 feature branches.
`llm_auto`/`llm_assist` currently route to SUBMITTED; Phase 4 takes them over.

Original work items (for reference):
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

## Phase 4 — LLM verification  ✅ done

**Goal:** auto-pass and auto-fail both work end to end; killing the LLM container routes new
submissions to `NEEDS_REVIEW` with an error note and **zero** incorrect ledger entries.

**Accepted:** migration `0004` (`verification_jobs` + occurrence `prompt_token` /
`verification_error`); `queue.py` (FOR UPDATE SKIP LOCKED, retry-to-3-then-park,
requeue-stuck); `anti_cheat.py` (dHash dedup over 120 d, EXIF staleness, NO_EXIF,
screenshot heuristic); `verification/` package (prompts + schema from §7.3, httpx client
with one repair retry, verdict banding); `worker/verify.py` pipeline wired into the
minute tick; `just eval` calibration harness. `llm_auto` auto-terminates, `llm_assist`
always routes to review, infra errors fail open with no ledger write. `just test` green
(132 tests). Shipped over 5 feature branches.

Original work items (for reference):
1. Migration `0004`: `verification_jobs` (state, attempts, `locked_at`).
2. `app/worker/queue.py` — claim jobs with `FOR UPDATE SKIP LOCKED`; retry policy; requeue
   rows `running` > 10 min on startup.
3. `app/services/anti_cheat.py` — pHash Hamming-distance search over last 120 days
   (`DUPLICATE_SUSPECTED`), EXIF `DateTimeOriginal` vs receive time > 15 min (`STALE_CAPTURE`),
   missing EXIF (`NO_EXIF`), screen-aspect + no camera make/model (`SCREENSHOT_SUSPECTED`),
   gallery-upload source (`GALLERY_UPLOAD`). Any flag → force `NEEDS_REVIEW`.
4. `app/services/verification/prompts.py` (shared with Phase 0) + `build_prompt(chore, photo)`
   from `verification_checklist` (the only input; `verification_rule` was removed — spec §4.1).
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
8. ~~Randomized prompt token~~ — shipped in Phase 4, removed later; see spec §6.1 item 5.
9. `GET /health/llm` — VLM reachability. `just eval` — run the Phase 0 labeled set against the
   current prompt, report precision/recall per chore type.
10. `verification_mode` respected everywhere: `llm_auto`, `llm_assist` (LLM suggests → all to
    review), `manual`, `auto_accept` — switchable with **no code changes** (§7.2 fallback).
11. Tests: auto-pass + auto-fail happy paths; LLM down → `NEEDS_REVIEW`, no ledger row;
    resubmitted identical photo flagged; missing token fails token check on a token-enabled chore.

**Accept when:** all four acceptance scenarios above pass.

---

## Phase 5 — Kid PWA  ✅ built (device sign-off pending)

**Goal:** installable and verified on **one iPhone + one Android**; full chore lock-screen →
verdict in < 60 s; airplane-mode submission uploads on reconnect; both check-in automations fire.

**Accepted (code):** Vite + React + TS + Tailwind + `vite-plugin-pwa`, all assets bundled
locally. Backend: per-kid `/checkin/{token}` geofence webhook (migration `0005`) and
Web Push + notification log (migration `0006`, `pywebpush`, best-effort, never blocks the
state machine). Kid `/me/*`: today/week/history lists, `getUserMedia` capture with labeled
slots + downscale + permission recovery + gallery escape hatch, IndexedDB offline queue,
location check-in, verdict view (no confidence/flags), redo/dispute, balance + statement,
read-only rules, VAPID subscribe gated on Home-Screen install. Admin `/admin/*`: review
inbox + split detail (signed media, EXIF/flags, raw model I/O), decisions + bulk approve,
chores CRUD + preview, kids & money + payouts + CSV, ops dashboard (queue depth, stuck
jobs, check-in staleness). `just test` (147 backend) + `npm test` (10 Vitest) green;
`just web-serve` builds + serves the PWA.

**Remaining:** the on-device acceptance run (spec §14.5) — captured in
`docs/device-checklist.md`; can't be done from CI.

Original work items (for reference):
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

## Phase 6 — Hardening & operations

**Goal:** a restore from last night's backup into a clean env reproduces all balances exactly;
a security scan shows no unauthenticated endpoint other than `/health` and `/checkin/{token}`.

Work items:
1. ✅ Security headers / CSP: strict CSP, HSTS + `preload`, `Secure` cookies in prod, no
   directory listing, `/docs` off in prod — in the Caddy `proxy` + app middleware.
   ✅ **`cloudflared` service + Cloudflare Access** — `docker-compose.prod.yml`,
   [remote-access.md](remote-access.md).
2. ✅ Operator path: **LAN / physical only, no Tailscale** (spec §12.2 `[D]`). The tunnel
   overlay binds `api` + `db` to `127.0.0.1`; `llama-server` stays on the LAN. ✅ Identity is
   Google via Cloudflare Access: the whole `/api/v1` surface requires a verified
   `Cf-Access-Jwt-Assertion` when `CF_ACCESS_*` is set, bar `/health`, `/checkin/{token}`
   and the break-glass `/auth/login` (which Caddy 404s so it never rides the tunnel).
3. ✅ Rate limits across auth + `/checkin`: 10/min/IP and per-account exponential backoff
   on the break-glass login, 20/hour/token **and** 10/min/IP on the check-in webhook — the
   per-IP cap is what throttles token *guessing*, since every guess lands in a fresh
   per-token bucket. Counters are in-process, not Postgres-backed: one `api` replica serves
   every request, so a shared store buys a round-trip and nothing else. The maps are swept
   and hard-capped because `/checkin/{token}` is unauthenticated, Access-bypassed, and
   keyed by whatever the caller sends (`app/auth/ratelimit.py`).
4. Retention jobs (worker cron-style ticks): photos → after `MEDIA_RETENTION_DAYS` (180)
   delete original, keep 256px thumbnail + verdict (Q2 default); geo points → 30 days.
5. ✅ **Backup + tested restore** — `just backup` (pg_dump `-Fc` + `MEDIA_ROOT` archive +
   a manifest of row counts and per-child balances), `just restore-verify` (throwaway
   Postgres, balances compared, touches nothing) and `just restore` (typed confirmation).
   Documented in [docs/restore.md](restore.md).
   ⬜ **Off-box shipping is NOT done:** backups are local and manual, so the spec §5 wording
   ("nightly ... rsync to TrueNAS") is not yet satisfied. restore.md names the two ways to
   close it.
6. `GET /admin/jobs` dashboard — queue depth, failures, last tick; alert when the scheduler
   has not ticked (staleness check + push to admin).
7. Structured JSON logging with actor / timestamp / before-after on every admin override,
   ledger entry, and model call (§5 auditability).
8. Startup reconciliation flags occurrences that expired during a known outage window
   (admin bulk-excuse affordance).
9. Tests: ✅ endpoint-inventory test asserting every route requires auth except the
   documented exceptions (`backend/tests/test_endpoint_inventory.py`).
   ✅ backup→restore balance equality — implemented as `just restore-verify` rather than a
   pytest case: the check is only meaningful against a real `pg_dump`/`pg_restore` pair, and
   pinning CI to a Postgres client matching the server major buys a brittle test for a
   guarantee the recipe already makes on demand, against real backups.

**Accept when:** the two acceptance criteria above pass.

---

## Phase 9 — Manual penalties  ✅ done

Not every consequence is an unfinished chore. A parent needs to charge for a house rule that
was broken at a moment nobody scheduled — and the kid needs to have read the price first.

1. `ChoreKind.penalty`: a chore that is a published price list, validated by `_check_penalty`
   in `app/schemas/chore.py` — money tiers only, all negative, `fixed`/`all` assignment, no
   schedule and no proof. Occurrence generation already filters on `chore_kind = scheduled`,
   and the cadence grammar gained an inert `penalty` token as defence in depth.
2. `ledger_entries.chore_id` (nullable, SET NULL): what lets an entry with no occurrence name
   the rule it came from, so the statement join resolves a chore through either path.
3. `app/services/penalties.py` — `apply()` writes one negative `penalty` entry (append-only,
   deliberately not idempotent), plus an audit row and a notification to the kid alone;
   `reverse()` undoes one through the existing `ledger.reverse_entry`.
4. `POST /penalties` and `POST /penalties/{entry_id}/reverse`, both admin.
5. PWA: a penalty kind in the chore form with a cost-only tier editor, a `PenaltyApply` panel
   behind a confirm, "Undo this" on manual penalty rows in the parent's statement, and a
   "Costs you money" section on the kid's rules screen.

**Accept when:** a parent creates a rule, charges it, and the kid's balance and statement both
move; the kid sees the rule and its price before it is ever charged; a sibling sees neither;
undoing restores the balance with the original charge still on the statement. See spec §4.8.

---

## Phase 7 — Nice-to-haves (backlog, not scheduled)

Streaks + bonus multipliers; sibling leaderboard (Q1); chore trading with parent approval;
weekly email/Push digest; savings goals; recurring
auto-payout on Sundays. Keep as a backlog file `docs/backlog.md`; do not build in this pass.

---

## Open questions — implement the stated default + `TODO(decision)` (spec §15)

Q1 no cross-child visibility · Q2 180 d then thumbnail+verdict · Q3 allow negative balance ·
Q6 filesystem content-addressed media · Q7 assume ages 10–15 ·
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
  and both kids via the API / a curl script.
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
  `DUPLICATE_SUSPECTED`;
  `just eval` prints precision/recall.
- **Phase 5:** run the manual device checklist on one iPhone + one Android — install to home
  screen, capture, Web Push delivery, camera-permission recovery, airplane-mode submit →
  reconnect upload, and both geofence automations hitting `/checkin/{token}`.
- **Phase 6:** `just backup` then `just restore` into a fresh compose stack; diff every
  child balance — must be identical. Run an endpoint-inventory test / external scan; only
  `/health` and `/checkin/{token}` may be unauthenticated.
