# ChoreKeeper — Self-Hosted Chore Tracking & AI Verification

**Status:** draft spec v0.1 — intended as the root context document for coding agents.
**Owner:** Dima
**Deployment target:** home LAN, Docker Compose, local OpenAI-compatible LLM, exposed to Internet via tunnel.

---

## 0. How to use this document

This is written to be handed to an implementation agent. Sections 1–13 are the spec.
Section 14 is a phased build plan; each phase has explicit acceptance criteria that can be turned
into tickets. Section 15 lists decisions that are still open — an agent should implement the
**stated default** and leave a `TODO(decision)` comment rather than inventing an alternative.

Conventions used below:
- **MUST / SHOULD / MAY** — RFC 2119 sense.
- `[D]` marks a design decision with rationale, so agents don't relitigate it.
- `[Q]` marks an open question with a default.

---

## 1. Goals & non-goals

### Goals
1. Parent (admin) defines recurring chores with schedule, proof requirements, verification rules and money value.
2. Kids submit proof from a phone (photo / location / checkbox) inside a time window.
3. A **local vision LLM** evaluates photo proof against a natural-language rule and returns a verdict + confidence + reasoning.
4. Parent reviews anything the model is unsure about, and can override any verdict.
5. Every completion/miss creates an immutable money ledger entry; parent tracks balances and records payouts.
6. Photos of the kids and the house are stored and scored at home — no third-party model, analytics or CDN ever sees them. Two named exceptions transit the public internet and nothing else does: the Cloudflare edge, which terminates TLS on the way to your browser (§12.2), and OpenStreetMap tiles in the admin geofence picker (§6.2).

### Non-goals (v1)
- Multi-family / multi-tenant SaaS. Single household, hardcoded tenancy.
- Native mobile apps. A PWA is the client.
- Background location tracking (see §6.2 — this is a hard constraint, not a laziness call).
- Gamification beyond money — points, streaks, badges, leaderboards (a v2 nice-to-have).
  `[D]` Non-money **outcomes** are in scope: a chore may carry parent-authored
  condition→outcome tiers whose outcome is a plain sentence ("grounded until the missing
  work is in"). These are consequences a parent already imposes, written down — not a
  points economy. The bright line: no score, no streak, no badge, no cross-kid comparison.

---

## 2. Actors

| Actor | Description | Access |
|---|---|---|
| **Admin** | Parent. Full CRUD on everything, approves/overrides, records payouts. | Full |
| **Child** | Daughter. Sees own assignments, submits proof, sees own balance. | Scoped to self |
| **System** | Scheduler + verification worker. | Internal |

`[D]` Two roles only. No "co-parent read-only" role in v1; a second admin account is just another admin.

---

## 3. Domain model (conceptual)

The single most important modeling decision:

`[D]` **Separate the chore *definition* from the materialized *occurrence*.**
A `Chore` is a rule ("kitchen, daily, 8am, alternating weeks, $2"). The scheduler materializes
`ChoreOccurrence` rows — one concrete instance per due datetime with a resolved assignee. All
proof, verification, money and history hang off the *occurrence*, never the definition. This means:
- editing a chore definition never rewrites history,
- assignee rotation is resolved once and is auditable,
- "what was due yesterday" is a plain indexed query, not a recurrence-rule evaluation.

```
Household
  └── User (admin | child)
  └── Chore (definition: schedule, proof spec, verification rule, money)
        └── ChoreOccurrence (assignee, window_open_at, due_at, status)
              ├── Submission (1..n attempts: photo/location/ack + client metadata)
              │     └── Verification (llm | manual: verdict, confidence, reasoning, raw model output)
              └── LedgerEntry (0..n: earning, penalty, adjustment)
  └── LedgerEntry (also: payout entries not tied to an occurrence)
```

### Occurrence state machine

```
        scheduler                submit                  verify (auto)
PENDING ─────────► OPEN ──────────────► SUBMITTED ──────────────► VERIFIED_PASS
                    │                       │                  └─► VERIFIED_FAIL
                    │                       └──────────────────────► NEEDS_REVIEW
                    │ due_at + grace passes                              │ admin acts
                    └──────────────────────► MISSED                      ▼
                                                            APPROVED / REJECTED (manual, terminal)
                                                            EXCUSED (admin, terminal, no money impact)
```

Rules:
- Only `OPEN` (and `NEEDS_REVIEW`/`VERIFIED_FAIL` if resubmission is allowed) accept new submissions.
- `MISSED` is set by the scheduler, not by a user action.
- Any state can be moved to `APPROVED`, `REJECTED` or `EXCUSED` by an admin. This always writes an
  audit record and a compensating ledger entry — **never** an update to an existing ledger row.
- Terminal states are frozen after `settlement_locked_at` (set when a payout covering that period is recorded).

---

## 4. Functional requirements

### 4.1 Admin — chore definition

Admin MUST be able to define a chore with:

| Field | Notes |
|---|---|
| `title`, `description` | Description is also shown to the kid. |
| `assignment_mode` | `fixed` (one kid), `rotating` (alternate on a period), `anyone` (first to complete claims it), `all` (each kid gets own occurrence). |
| `rotation_period` | For `rotating`: `weekly` / `biweekly` / `daily`. Plus `rotation_anchor_date` and ordered `assignee_ids` — this is what makes "every other week" deterministic. |
| `cadence` | `daily`, `weekdays`, `weekends`, `weekly(on=[SAT])`, `monthly(day=N)`, `once(YYYY-MM-DD)`, `standing`, `custom_rule`. `[D]` A one-off carries its date **inside the token**, not in `start_date`: occurrence generation only ever passes the cadence its clamped `[max(start_date, today), horizon]` window (§8.1), so a date-less `once` would fire on every tick forever for a chore with no `end_date`. Keeping it in the token also leaves a one-off reschedulable — `cadence` is patchable, `start_date` is not. |
| `window_opens` | Relative to due time, e.g. `-12h` — kid can't submit tomorrow's kitchen photo at 3pm today. |
| `due_time` | Local wall-clock time, e.g. `08:00`. Timezone is household-level. |
| `grace_period` | e.g. `15m`. Late-but-within-grace = pass with `was_late` flag (optionally reduced payout). |
| `start_date`, `end_date` | `end_date` nullable = open-ended. |
| `proof_type` | `photo` (1..n photos), `location`, `photo+location`, `acknowledgement`, `none` (parent-verified only). |
| `photo_count` / `photo_prompts` | e.g. `["kitchen sink close-up", "wide shot of counters"]` — the kid sees these as labeled capture slots. Two labeled photos verify far better than one vague one. |
| `verification_mode` | `llm_auto`, `llm_assist` (LLM suggests, parent confirms all), `manual`, `auto_accept`. |
| ~~`verification_rule`~~ | `[D]` **REMOVED.** A free-text rule was never sent to the model as itself: `worker/verify.py` only used it as a fallback when the checklist was empty, wrapping it in a single required check, and ignored it entirely once any check existed — so a parent who wrote both silently lost the rule. The checklist is now the only input (§7.3, and "checklists beat vibes" in §6.3). Reinstating it means a migration, a `build_task_prompt` argument, and a decision about what it means alongside a checklist. |
| `verification_checklist` | Optional array of atomic boolean checks. The model answers each; the verdict is derived. Much more reliable than one fuzzy prompt (see §7.3). |
| `auto_pass_threshold` / `auto_fail_threshold` | Confidence bands. Between them → `NEEDS_REVIEW`. Defaults 0.85 / 0.35. |
| `geofence` | For location proof: lat, lon, radius_m, plus `arrive_before` time. |
| `chore_kind` | `scheduled` (a recurring rule) or `standing` (a state a parent flips, §4.7). Immutable after save — duplicate to change it. |
| `outcome_tiers` | Optional ordered condition→outcome list for a chore a person grades (§4.6). Replaces `reward_amount`/`penalty_amount` for that chore; never mixed with them. |
| `reward_amount` | $ credited on pass. Unsigned magnitude. |
| `penalty_amount` | $ debited on miss/fail. Default 0 — penalties are opt-in per chore. `[D]` An **unsigned magnitude**, not a signed amount: the API rejects a negative and `debit_penalty` applies the sign. (A tier's `amount_cents` is the opposite — signed — because one tier list carries both rewards and penalties; see §4.6.) |
| `late_multiplier` | e.g. 0.5 for within-grace-but-late. Default 1.0. |
| `active` | Soft disable without deleting history. |

Admin MUST also be able to: preview the next N generated occurrences before saving; clone a chore;
and edit a chore with a choice of **"apply from today forward"** (default) vs **"apply to all future
already-generated occurrences"**.

### 4.2 Admin — review

- Inbox view of everything in `NEEDS_REVIEW`, `SUBMITTED`, and recent `VERIFIED_FAIL`, sorted by due date.
- Per-occurrence detail: photos (full-size, EXIF/metadata panel), the exact prompt sent to the model,
  the model's raw response, confidence, per-checklist answers, submission timestamps, and any anti-cheat flags.
- Actions: **Approve**, **Reject**, **Excuse**, **Request redo** (reopens window with a note), **Adjust amount** (with a required reason).
- Bulk approve from a list view.

### 4.3 Admin — money

- Per-kid balance = sum of ledger entries. Ledger is **append-only**.
- Entry kinds: `earning`, `penalty`, `bonus`, `adjustment`, `payout`.
- Statement view per kid, filterable by date range, exportable to CSV.
- "Record payout" writes a negative `payout` entry with method + note, and sets `settlement_locked_at`
  on all occurrences in the covered period.
- Weekly summary: earned / missed / pending, per kid.

### 4.4 Child

- Home = today's list, "due in X", with big capture buttons; then this week; then history.
- Submitting: in-app camera capture → preview → optional note → submit. Progress/spinner while the
  model runs (target < 20s; if longer, show "we'll let you know" and rely on push).
- Sees verdict, and for a fail, sees the model's reason in kid-friendly language ("There are still
  two cups in the sink"). This is the single highest-value UX feature — it turns the app from a
  scorekeeper into a checklist.
- Sees own balance and statement. Cannot see the sibling's balance `[Q1]`.
- Can request a redo or dispute a verdict (creates an item in the admin inbox with a note).

### 4.5 Notifications

- Web Push (VAPID). Kid: window opening, T-30min reminder, verdict, redo requested.
- Admin: item needs review, chore missed, dispute filed, daily 8:05am digest.
- All notification sends are logged; a failed push MUST NOT block the state machine.

---


### 4.6 Tiered outcomes

A chore whose result a **person** grades, with more than two possible outcomes, carries an
ordered list of condition→outcome tiers instead of a single reward/penalty pair. The parent
picks exactly one at review time.

    all A grades      -> +$100
    at least one B    -> +$50
    at least one C    -> -$50
    more than one missing assignment -> "grounded until it's fixed"

Each tier is `{id, condition, outcome_kind: money|text, amount_cents?, text?}`. `condition` is
free text assessed by a person — there is no condition language to evaluate.

- `[D]` **Manual only.** A tiered chore MUST use `verification_mode: manual`. The LLM modes
  are rejected (a model cannot judge "all A grades", and under `llm_auto` its opinion would
  move money), and so is `auto_accept` (it passes terminally with no human in the loop, so no
  tier would ever be picked). A tier is chosen by a person.
- `[D]` **Never mixed with the classic channel.** A tiered chore's `reward_amount`,
  `penalty_amount` and `late_multiplier` MUST be 0/0/1.0, and it carries no
  `verification_checklist`. Enforced at validation, so "tiers are an
  additional mechanism" is a rule rather than a convention.
- `[D]` **A tier's `amount_cents` is signed** (negative = penalty), unlike the unsigned
  `reward_amount`/`penalty_amount` — one list carries both, and the sign is what routes the
  ledger kind. The admin form offers a reward/penalty toggle and applies the sign itself; a
  parent never types a minus.
- `[D]` **No new occurrence status.** A tiered decision lands on the existing terminal
  `APPROVED` plus the recorded tier. The UI renders the tier's condition where it would
  otherwise say "Approved" — "approved" reads wrong on a -$50 outcome.
- `[D]` **The occurrence snapshots the tier list at generation**, exactly as it snapshots the
  money terms (§3). Editing "+$100" down to "+$50" must not re-price a report card the kid
  already handed in.
- Any proof type is allowed: manual grading and photo evidence are orthogonal, and a photo of
  a report card is exactly the evidence such a chore wants.


### 4.7 Standing chores

Some household rules are **states, not events**: "more than one missing assignment → grounded
until it's fixed". A parent switches it on and it stays on until switched back. There is no
due time, no proof, no window and nothing to submit.

`chore_kind: standing` is that chore. It carries `outcome_tiers` (text only) saying what is in
force, plus `standing_on` / `standing_tier_id` / `standing_since`.

- `[D]` **No occurrences, no submissions, no ledger entries.** Occurrence generation filters on
  `chore_kind = scheduled`. As defence in depth the cadence grammar also accepts an inert
  `standing` token that returns no dates, so a standing chore generates nothing even if some
  future code path forgets the filter. Its `cadence` is therefore a *correct* value, not a
  dummy one.
- `[D]` **Text outcomes only.** A standing chore moves no money: `reward_amount`,
  `penalty_amount` and `late_multiplier` MUST be 0/0/1.0, and every tier must be
  `outcome_kind: text`. The consequence is a sentence a parent wrote.
- `[D]` **Every flip is recorded** in `chore_state_events` with actor, timestamp, a snapshot of
  the tier put in force, and an optional note — *and* in the audit log. Two records because
  they have two audiences: the audit log is the admin forensic trail and is never shown to a
  child, while the event table is what tells a kid what is in force and since when. Flipping to
  the state it is already in is a no-op, so a double tap doesn't litter that history.
- `[D]` **`chore_kind` is immutable.** Switching a saved chore between kinds would strand its
  occurrences; clone it instead (§4.1).
- `[D]` **Deactivating turns it off first.** A retired chore must not leave a live consequence
  on the kid's home screen.
- The schedule and proof columns are NOT NULL, so the API fills them (`cadence: standing`,
  `due_time: 00:00`, `proof_type: none`, `verification_mode: manual`) when a standing chore
  omits them. Absent keys only, so a PATCH round-trip can never drift them.
- The child sees current state through the existing `GET /chores` (§15 Q8) — no new kid
  endpoint — rendered as a banner on their home screen.

## 5. Non-functional requirements

- **Locality:** no image, location point, or prompt may be *sent to* a third-party service. Scoring is a local vision LLM; no third-party analytics, no CDN-hosted fonts/JS — vendor everything. The two deliberate exceptions are named in §1 goal 6: photo bytes transit the Cloudflare edge in flight (§12.2, never stored there), and OSM serves map tiles to the admin picker (§6.2). Cloudflare and Google additionally hold *identity* — who signed in and when (§12.1) — never chore content.
- **Availability:** best-effort home hosting. A missed scheduler tick MUST be recoverable — the scheduler is idempotent and backfills on startup (see §8.3).
- **Retention:** photos default 180 days, then deleted while retaining verdict + thumbnail `[Q2]`.
- **Backup:** Postgres nightly `pg_dump` + object store rsync to TrueNAS. Restore procedure documented and tested in Phase 6.
- **Auditability:** every admin override, every ledger entry, every model call is recorded with actor, timestamp, and before/after.
- **Latency:** UI actions < 300ms p95 excluding model inference. Verification p95 < 30s.
- **Privacy:** it's a camera pointed at your kids' bedrooms. Photos are stored outside the web root, served only through authenticated, short-lived signed URLs, and never listed by directory index.

---

## 6. The hard parts (read before designing anything)

These three sections are where naive implementations fail. Design decisions here are binding.

### 6.1 Photo proof is trivially gameable

A motivated 12-year-old will: reuse yesterday's photo, screenshot a photo from the family album,
photograph a clean corner of a messy room, or ask a friend to send a picture of *their* clean sink.
Mitigations, in order of value:

1. `[D]` **In-app camera only. DECIDED: strict.** The capture surface is `getUserMedia` rendered inside the PWA — a live viewfinder with a shutter button, frame grabbed to canvas. The `<input type="file" capture>` path is **not** used as the primary flow: on iOS the `capture` attribute is inconsistently honored and still exposes a library picker in several versions, so it is not a real constraint. File input exists only as an admin-enabled per-chore escape hatch (`allow_gallery_upload`, default false), and any submission arriving through it is flagged `GALLERY_UPLOAD` and forced to `NEEDS_REVIEW`.
   - Requires HTTPS (satisfied by the tunnel) and works in installed PWAs on iOS 14.3+ and Android Chrome.
   - Handle camera-permission-denied with a clear recovery screen, not a dead end.
   - A screenshot-of-a-screen still defeats this alone; it is the floor, not the ceiling.
2. `[D]` **Perceptual hash (pHash) dedup.** Compute a pHash on ingest; compare against the last 120 days of submissions for that household. Hamming distance below a threshold → flag `DUPLICATE_SUSPECTED`, force `NEEDS_REVIEW`. Catches reuse, which is the most common cheat.
3. `[D]` **Server-side capture timestamp is authoritative.** Client EXIF timestamps are advisory only. Record server receive time, and flag when EXIF `DateTimeOriginal` is more than 15 minutes older than receive time (`STALE_CAPTURE`).
4. **Metadata flags — gallery uploads only.** Missing EXIF entirely (common for screenshots and downloads) → `NO_EXIF`; image dimensions matching a phone screen aspect + no camera make/model → `SCREENSHOT_SUSPECTED`. `[D]` **These run only on `source=gallery`.** The in-app capture required by item 1 grabs a frame to a canvas and encodes it with `toBlob`, which yields a JPEG with *no* EXIF at any ratio the camera track happens to deliver (typically 4:3 or 16:9) — so both heuristics fired on every honest submission, forcing it to `NEEDS_REVIEW` and burying the model's verdict. They can only carry information about a file the kid chose, so that is the only place they run; a picked JPEG is forwarded to the server unmodified (up to 6MB) so there is real metadata to judge. Camera captures stay covered by items 2, 3 and 5.
5. `[D]` ~~**Randomized prompt token.**~~ **REMOVED.** Built in Phase 4, then taken out: it required the household to keep a second screen or whiteboard in frame for every photo, which is friction on every honest submission to catch a cheat that had not happened. Nothing replaces it, so a screenshot of an old photo displayed on another screen is defeated only by pHash dedup (item 2) and a parent's eyes — accepted knowingly. The `chores.prompt_token_enabled` and `chore_occurrences.prompt_token` columns are dropped; reinstating it means a new migration, the scheduler stamp, a checklist item in `build_task_prompt`, and the capture-screen pill.
6. **Multi-angle:** requiring two labeled shots (sink close-up + wide kitchen) makes staging meaningfully harder for near-zero extra effort.

All flags are surfaced in the admin review panel and are inputs to the routing logic — they do **not**
auto-fail. False accusations are worse than a missed cheat.

### 6.2 Location proof is weaker than it looks

`[D]` Do not promise "confirm she arrived at school by 8:05." A web app cannot do this reliably:

- iOS Safari/PWA has **no background geolocation**. The Geolocation API only fires while the page is open and foregrounded.
- Geolocation is spoofable on Android (mock location providers, no root needed on a developer-options-enabled device).
- School buildings have poor GPS; expect 50–150m error indoors, sometimes wifi-derived positions hundreds of meters off.

Therefore v1 implements **active check-in**, not tracking:
- The kid taps "I'm at school" inside a window (e.g. 07:30–08:10). The app captures `position` with `enableHighAccuracy: true`, records lat/lon/accuracy/timestamp, and computes distance to the geofence centroid.
- Pass if `distance - accuracy <= radius`. Flag `LOW_ACCURACY` if `accuracy > 100m` → `NEEDS_REVIEW`.
- Missing check-in by the deadline → `MISSED`, notification to admin. The real signal is "she didn't check in," which correlates well enough with "she isn't there" to be useful.
- Store a **coarse** point (4 decimal places, ~11m) plus the boolean result. Do not build a location history you don't need — retention 30 days.
- `[D]` **Defining the fence is a map picker in the admin UI**, with a draggable pin, a radius the parent can see drawn to scale, "use my current location", and a paste box that reads coordinates out of a Google/Apple Maps link. The one deliberate exception to §1 goal 6: **map tiles are fetched from `tile.openstreetmap.org`**, which learns the coordinates a parent is viewing. Scoped as tightly as it can be — Leaflet is bundled from npm (so `script-src 'self'` is unchanged), the map is a lazy chunk that loads only when a location chore's editor is open, `img-src` is the only CSP directive that names the host, and no photo, name or chore data goes with the request. The lat/lon/radius inputs stay authoritative and work with the map blank, which is what an offline household sees. Address *search* is deliberately not offered: geocoding would ship the household's address to a third party on every keystroke.

If genuinely accurate arrival tracking matters, the right tool is an OS-level geofence automation.
The app MUST expose a per-kid `POST /api/v1/checkin/{token}` webhook so this can be wired up outside
the browser. **Devices are mixed, so both paths must be documented and tested:**

- **iPhone:** Shortcuts → Automation → "When I arrive at [School]" → *Get Contents of URL* (POST, JSON body).
  Set "Run Immediately" so it fires without a notification tap. Arrival automations are reliable but can
  lag several minutes; set the geofence radius generously and the window accordingly.
- **Android:** no first-party equivalent. Options, in order of preference: **Tasker** (Location profile →
  HTTP Request task, ~$3, most reliable), **MacroDroid** (free tier is sufficient), or the **Home Assistant
  companion app** if HA is already on the LAN — its `zone.enter` trigger is the cleanest of the three and
  fits the existing self-hosted stack.
- Both paths need battery-optimization exemptions for the automation app, or arrivals silently stop firing
  after a few weeks. Add a "last check-in seen" staleness warning to the admin dashboard so a broken
  automation surfaces as a config problem rather than as a kid getting penalized.

`[D]` The webhook token is per-kid, high-entropy, revocable, and rate-limited to 20 req/hour. It can only
transition a `location` occurrence that is currently `OPEN` — it can never approve a photo chore or write
an arbitrary ledger entry. Assume the token leaks eventually.

### 6.3 The LLM will be wrong, and it will be wrong asymmetrically

A local VLM judging "is this room clean" is doing a subjective, underspecified task with no ground truth.
Expect it to be over-lenient on cluttered-but-not-dirty rooms and to hallucinate objects that aren't there.

`[D]` Binding rules:
1. **The model is an assistant, not a judge.** Its output is a *recommendation with confidence*. Parent override is always one tap away, and every kid-facing message says the parent has the final say. Do not build a system where a child's allowance is decided solely by a 30B model's opinion of a photograph.
2. **Confidence banding, not thresholding.** Above `auto_pass_threshold` → pass. Below `auto_fail_threshold` → fail. In between → `NEEDS_REVIEW`. Any anti-cheat flag → `NEEDS_REVIEW` regardless of confidence.
3. **Fail-open on infrastructure errors.** If the LLM endpoint is down, times out, or returns unparseable output after retries, the occurrence goes to `NEEDS_REVIEW` with `verification_error`, never to `VERIFIED_FAIL`. The kid must never lose money because llama.cpp OOMed.
4. **Checklists beat vibes.** Decompose the chore's criteria into atomic yes/no questions. "Are there dishes in the sink basin?" is answerable; "is the kitchen clean?" is not. Verdict = all required checks pass. Confidence = min of per-check confidences.
5. **Log everything.** Store the full request (prompt, model name, params, image hashes) and the raw response for every call. This is what lets you tune prompts later and defend a verdict at the dinner table.
6. **Calibration harness.** Ship a `just eval` target that runs a labeled folder of past submissions against the current prompt and reports precision/recall per chore type. Prompt changes without this are guesswork.

---

## 7. Verification pipeline

### 7.1 Flow

```
Submission created
  └─► ingest: strip/record EXIF, normalize orientation, resize to max 1568px long edge,
             re-encode JPEG q85, compute sha256 + pHash, write to object store
  └─► enqueue verification job (Postgres queue, FOR UPDATE SKIP LOCKED)
  └─► worker:
        1. anti-cheat checks (pHash neighbors, EXIF age, screenshot heuristics)
        2. build prompt from chore.verification_checklist
        3. POST /v1/chat/completions to VLM with base64 image(s), JSON schema response
        4. parse + validate against schema; on failure retry once with a repair prompt
        5. derive verdict + confidence; apply banding + flags
        6. write Verification row, transition occurrence, write LedgerEntry on terminal pass/fail
        7. push notification
```

`[D]` Resize before inference. Sending a 12MP phone photo to a VLM wastes tokens and time for no
accuracy gain; most VLMs downsample internally anyway. 1568px long edge is a good ceiling.

### 7.2 Model call

OpenAI-compatible, so it works against llama.cpp `llama-server`, vLLM, or Ollama unchanged:

```python
POST {LLM_BASE_URL}/v1/chat/completions
{
  "model": "{LLM_VISION_MODEL}",
  "temperature": 0.1,
  "max_tokens": 700,
  "response_format": {"type": "json_schema", "json_schema": {...}},
  "messages": [
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": [
      {"type": "text", "text": task_prompt},
      {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
    ]}
  ]
}
```

**Model requirement:** this needs a *vision* model, which is a separate llama-server instance from a
text model — `llama-server` serves one model per process. Plan for a second container/port
(`LLM_VISION_BASE_URL`) with an mtmd-capable GGUF + its mmproj file. Candidates worth benchmarking on
the target GPU: Qwen VL series, Gemma vision variants, InternVL, MiniCPM-V. Verify current mtmd
support and mmproj availability before committing — llama.cpp multimodal support moves fast, and
Vulkan backends occasionally lag CUDA for vision projectors. **Phase 0 of the build plan is a
model bake-off; do not architect around a model you haven't run.**

Fallback: if no local VLM performs acceptably, `verification_mode: llm_assist` degrades the product
gracefully to "parent reviews everything, sorted into a nice queue" — still useful. The architecture
MUST support this without code changes.

### 7.3 Prompt structure

```
SYSTEM:
You are a household chore verification assistant. You examine photographs and answer
specific factual questions about what is visible. You are strict about only reporting what
you can actually see. If an area is not visible in the photo, answer "unclear" rather than
guessing. You never speculate about who did the chore or make judgments about people.
Respond only with JSON matching the provided schema.

USER:
Chore: {chore.title}
Photo label: {photo_prompt}   e.g. "kitchen sink close-up"

Answer each check:
1. Is the sink basin free of dishes, cups, pans and utensils? (yes/no/unclear)
2. Is the countertop immediately around the sink free of dirty dishes? (yes/no/unclear)
3. Is the visible area free of food waste or spills? (yes/no/unclear)

For each: answer, confidence 0-1, and one sentence of evidence describing what you see.
Then an overall summary in one friendly sentence addressed to a child.
```

Response schema:

```json
{
  "checks": [{"id": 1, "answer": "yes|no|unclear", "confidence": 0.0, "evidence": "string"}],
  "overall_confidence": 0.0,
  "child_message": "string",
  "image_quality_issue": "none|too_dark|too_blurry|wrong_subject|too_close|too_far"
}
```

`[D]` `image_quality_issue != none` → do not fail. Return to the kid as "retake, the photo is too dark"
and leave the occurrence `OPEN`. This is the difference between a tool and an adversary.

`[D]` `unclear` counts as a fail for *required* checks but caps confidence at 0.5, routing to review.

---

## 8. Scheduling

### 8.1 Occurrence generation

A `generate_occurrences(horizon_days=14)` job runs hourly and on startup. For each active chore:
1. Compute due datetimes in the household timezone from `cadence` between `max(start_date, today)` and `today + horizon`.
2. Resolve assignee per date via `assignment_mode`.
3. Upsert on the unique key `(chore_id, due_at, assignee_id)` — idempotent by construction.

`[D]` 14-day horizon, not "generate everything to end_date". Keeps the table small, lets definition
edits take effect quickly, and bounds the blast radius of a bad rule.

### 8.2 Rotation math

Deterministic and testable — no "whose turn is it" state to drift:

```python
weeks_since_anchor = (iso_week_start(due_date) - iso_week_start(rotation_anchor_date)).days // 7
idx = (weeks_since_anchor // (2 if rotation_period == "biweekly" else 1)) % len(assignee_ids)
assignee = assignee_ids[idx]
```

Admin MUST be able to see a "next 4 weeks: Alice, Alice, Bea, Bea" preview when configuring, and to
**swap** an individual occurrence's assignee (kids trade weeks; the app should let them, with a log entry).

### 8.3 Missed-detection & catch-up

A separate minute-ticker transitions `OPEN` → `MISSED` where `now > due_at + grace`. Because this is a
query over state rather than a timer, a machine that was asleep for six hours catches up correctly on
the next tick. `[D]` No in-memory timers anywhere. All scheduling is "reconcile desired state from the DB."

Startup reconciliation MUST also: regenerate occurrences, requeue verification jobs stuck in `running`
for > 10 minutes, and log a summary of what it fixed.

### 8.4 Time handling

`[D]` Store all timestamps as `timestamptz` in UTC. Store the household timezone (`America/Los_Angeles`)
as config and do all cadence/wall-clock math in it. "Before 8am" means 8am local, across DST boundaries.
DST transition days are an explicit test case.

---

## 9. Money ledger

`[D]` **Tier money.** A money tier writes `earning` (positive) or `penalty` (negative) on
the first decision, so the `(occurrence_id, kind)` partial unique index still makes it
exactly-once against a double click. Changing the tier afterwards reverses the standing
entry and posts the new amount as an `adjustment` carrying `meta.tier_id` — the index is
never violated and nothing is updated in place. Re-selecting the *same* tier is a no-op,
guarded on `chore_occurrences.outcome_tier_id`; an `excuse` clears that field so a later
re-grade pays again. A text tier writes no ledger entry at all.

`[D]` Append-only, integer cents, no floats, no UPDATEs.

```
LedgerEntry:
  id, household_id, child_id, occurrence_id (nullable), kind, amount_cents (signed),
  currency, reason, created_by (user|system), created_at, reversed_by_entry_id (nullable)
```

- Correcting a mistake = insert a reversing `adjustment` entry and set `reversed_by_entry_id` on the original. History stays intact.
- Balance = `SELECT SUM(amount_cents) WHERE child_id = ?`. Cache it if it ever matters (it won't at this scale).
- Exactly-once earning: partial unique index on `(occurrence_id, kind)` where `kind IN ('earning','penalty')`. A double-clicked approve cannot double-pay.
- Payout entries are negative and carry `method` + `note` in metadata.

`[Q3]` Should penalties be allowed to drive a balance negative? Default: **yes, allow negative**, and
surface it prominently in the kid view. Alternative is clamping at zero, which quietly loses information.

---

## 10. API surface (v1)

REST, JSON, `/api/v1`. Auth via HTTP-only session cookie; CSRF token for mutations.

```
POST   /auth/login                       {username, password} → session
POST   /auth/logout
GET    /auth/me

GET    /children                          admin
GET    /children/{id}/balance             admin | self
GET    /children/{id}/ledger?from&to      admin | self

GET    /chores                            admin
POST   /chores                            admin
GET    /chores/{id}
PATCH  /chores/{id}                       ?apply=forward|future_generated
DELETE /chores/{id}                       soft delete
POST   /chores/{id}/duplicate             admin — clone a definition (§4.1); the copy starts inactive
POST   /chores/{id}/state                 admin — flip a standing chore on/off (§4.7)
GET    /chores/{id}/state/history         flip history, newest first; readable by the kid
POST   /chores/preview                    admin — returns next N occurrences for an unsaved definition

GET    /occurrences?from&to&status&child  admin | self(scoped)
GET    /occurrences/{id}
POST   /occurrences/{id}/submissions      multipart: files[], note, geo{lat,lon,accuracy}, client_meta
POST   /occurrences/{id}/decision         admin {action: approve|reject|excuse|redo|tier, tier_id?, amount_override_cents?, reason}
                                          tier picks one outcome tier (§4.6); approve/reject are refused for a tiered chore
PATCH  /occurrences/{id}/assignee         admin — swap
POST   /occurrences/{id}/dispute          child {message}

GET    /submissions/{id}/media/{n}        signed, short-TTL, authz-checked
GET    /verifications/{id}                admin — full raw model I/O

POST   /payouts                           admin {child_id, amount_cents, method, note, covers_through}
GET    /payouts

POST   /checkin/{kid_token}               unauthenticated-by-token, for iOS Shortcuts geofence
POST   /push/subscribe
GET    /health   /health/llm              liveness + VLM reachability
GET    /admin/jobs                        queue depth, failures, last tick
```

`[D]` Media served through the API with authz on every request, never as static files. Signed URL TTL 5 minutes.

---

## 11. Frontend

- **Stack:** React + TypeScript + Vite, TanStack Query, Tailwind. PWA via `vite-plugin-pwa` (installable, offline shell, Web Push).
- **Two shells** behind one auth: `/admin/*` (data-dense: tables, filters, review split-view) and `/me/*` (kid: large touch targets, one primary action per screen, no nested navigation).
- **Offline tolerance:** capture and queue a submission in IndexedDB if the network drops; retry on reconnect. School wifi is bad; this matters.
- **Upload:** client-side downscale to 1568px before upload — a 6MB upload over home DSL upstream is a bad experience.
- **Kid view MUST NOT** show model confidence numbers or anti-cheat flags. It shows the verdict, the friendly message, and a redo button. Confidence scores invite arguments.
- **Accessibility:** works one-handed, in a dark kitchen at 7:55am, on a cracked phone. Test at 320px width.

---

## 12. Auth, identity & remote access

### 12.1 Auth
`[D]` **Google identity, delivered by Cloudflare Access.** Everyone — parent and kids alike — signs
in with a Google account; Cloudflare authenticates them at the edge and the app maps the verified
`email` claim in the `Cf-Access-Jwt-Assertion` to a `users` row. There is no app password and no
TOTP.

This reverses the original decision ("local accounts, **not** OAuth — the whole point is no external
dependency"), and the reason is that the premise expired. Once §12.2 put the app behind Cloudflare,
Cloudflare became a hard dependency for remote access whether or not it held identity. Against that
baseline, a per-person password plus a per-person authenticator app buys very little: it is one more
secret per kid to lose, reset and share, and the household's Google accounts already carry 2FA that
is better administered than anything this app would ship. One fewer credential is the security win
here, not a loss.

- The parent-admin adds a kid by entering their Google address (`users.email`, unique per household).
  The same address must also be listed in the Access policy — the app is the second half of that pair,
  never the first.
- Sessions are unchanged: the app still mints its own server-side session + `ck_session` cookie and
  CSRF token from the verified identity, so revocation, CSRF and the 12h/90d lifetimes all still
  belong to the app. Access is the outer wall, not the session store.
- `[D]` **Access is authoritative about who is at the keyboard.** If a session cookie names one user
  and the Access assertion names another, the cookie is revoked and the assertion wins — otherwise a
  shared family tablet hands one child the previous child's screen.
- `[D]` **One local admin password survives as break-glass**, for when Cloudflare or Google is
  unavailable. It is admin-only, minimum 12 characters, and rate limited as before (10/min/IP,
  exponential backoff per account).
- `[D]` **Break-glass has its own LAN door** — a second Caddy site on `:81`, published to the home
  network and unreachable from the tunnel, since cloudflared's ingress names `proxy:80` and nothing
  else. The Access check is skipped there wholesale. Without that it is theatre: the login succeeds
  and then the gate refuses the session it just issued, so the documented way back in leads nowhere.
  Two independent layers keep it off the internet — the tunnel site answers `404` for
  `/api/v1/auth/login`, and Caddy stamps every proxied request with `X-CK-Door`, which the app
  honours only on an explicit `lan`, so a stripped or unrecognised value fails closed. App auth,
  CSRF and the rate limits are unchanged behind it; what the door grants is the chance to type the
  admin password, so everyone on the wifi gets to try. Kids cannot use it — their identity is
  Google, and Google is not in front of it.
- ~~`[Q4]`~~ **RESOLVED** — there is no kid password to reset. A parent changes the Google address
  from the admin panel, which revokes that kid's live sessions.

### 12.2 Remote access — DECIDED: Cloudflare Tunnel

`[D]` `cloudflared` runs as a compose service holding an outbound-only connection to Cloudflare. **No
inbound ports are opened on the Asus/Merlin router and no dynamic DNS is needed.** Concretely:

- One named tunnel, one hostname (e.g. `chores.example.com`), ingress → `proxy:80`.
- Tunnel token injected via env/secret; `cloudflared` has no access to the LAN beyond the mapped service.
- `[D]` **Cloudflare Access fronts the whole hostname, kids included** — Google is the only enabled login
  method, and the policy lists the household's addresses one by one. Free tier covers this.
  This replaces the earlier carve-out ("no Access on the kid paths — a login wall in front of a
  12-year-old at 7:55am guarantees the app gets abandoned"). The objection was to the *ceremony*, and
  Google + Instant Auth removes it: a signed-in phone passes through without a prompt, so the kid sees
  the chore list, not a wall. Meanwhile the carve-out was leaving the entire kid surface — photo upload,
  location, ledger — behind nothing but a password on the open internet.
- Two exemptions, each because there is no browser to redirect: `/api/v1/health` (liveness probe) and
  `/api/v1/checkin/{token}` (the iOS Shortcuts geofence webhook, which gets an Access **Bypass** policy
  and stays token-authenticated + rate-limited per §6.2). A stricter admin-scoped Access application
  covers `/admin` and `/api/v1/admin` with a parent-only policy and a shorter session; because each
  application issues its own AUD tag, `CF_ACCESS_AUD` is a comma-separated list.
- Disable caching for `/api/*` and media routes (cache rules or `Cache-Control: private, no-store`). A cached
  signed media URL served to the wrong session is the failure mode to avoid.
- Cloudflare's free-plan request body limit is 100MB — irrelevant given client-side downscaling to ~300KB,
  but note it before anyone adds video proof.
- WAF: rate-limit rule on `/api/v1/auth/login`, and a bot-fight exception for the PWA's service worker.

**Accepted tradeoff:** TLS terminates at Cloudflare, so photo bytes transit their edge on the way to your
browser. They are never *stored* there and the origin stays unreachable directly. For a household chore
app this is reasonable; if it later stops feeling reasonable, the migration path is Tailscale + MagicDNS
with the app unchanged.

`[D]` **The operator path is LAN and physical access only. No Tailscale, no second door.** SSH, Postgres
and `llama-server` are bound to the host's loopback or the LAN and have no remote path at all; only the
app is reachable from outside, through the tunnel. This replaces the earlier `[D]` that added Tailscale
for the operator surfaces: the parent-admin operates the app through Cloudflare, and a VPN mesh
maintained for the handful of times a year someone needs `psql` is a standing attack surface bought
with real upkeep. **Accepted consequence:** a fault that needs a shell cannot be fixed away from home.
That is also what the break-glass password (§12.1) exists for — it works on the LAN when the edge does
not.

Options considered:

| Option | Pros | Cons |
|---|---|---|
| **Cloudflare Tunnel** (`cloudflared`) + app auth | No open ports, no public IP needed, works on school wifi and locked-down devices, TLS handled | Traffic transits Cloudflare (TLS-terminated there) — for a household chore app this is an acceptable but real consideration; photos are only ever *requested* through it, but they do transit it |
| **Tailscale** on all devices | Zero trust, nothing public, traffic stays E2E encrypted between devices | Every kid's phone needs the app installed and running; a kid can "accidentally" disable it; MagicDNS + PWA install is fiddly |
| **Reverse proxy + port forward** on the Asus/Merlin router | Fully self-contained | Exposes an internet-facing surface with a home-grown auth layer; must manage certs, fail2ban, and CVEs yourself |

`[D]` The app assumes it is internet-reachable. Strict CSP, HSTS, secure/SameSite
cookies, no directory listing, and no debug endpoints in prod. The CSP names exactly one third-party host —
`https://*.tile.openstreetmap.org` in `img-src`, for the geofence map picker (§6.2). Everything
else, `script-src` and `connect-src` included, stays `'self'`.

---

## 13. Deployment

### 13.1 Services (docker-compose)

| Service | Image / build | Notes |
|---|---|---|
| `api` | FastAPI + uvicorn | REST, auth, media serving |
| `worker` | same image, different entrypoint | verification jobs + scheduler ticks |
| `db` | postgres:17 | volume on the SSD, nightly dump to TrueNAS |
| `web` | nginx serving built PWA | or served by Caddy alongside api |
| `proxy` | caddy | TLS, routing, security headers |
| `llm-vision` | llama.cpp server (external or composed) | separate port from any existing text model |
| `cloudflared` | tunnel | **required** — sole ingress path, see §12.2 |

`[D]` **Postgres, not MongoDB.** This app is a ledger plus a scheduler: it needs transactions across
occurrence-transition + ledger-insert, partial unique indexes for exactly-once payment, and
`SELECT ... FOR UPDATE SKIP LOCKED` for the job queue. Those are the exact things a relational DB is for.

`[D]` **No Redis.** Postgres is the job queue at this scale (single household, dozens of jobs/day).
One less moving part to back up and monitor.

Object storage: plain filesystem volume at `/data/media/{household}/{yyyy}/{mm}/{sha256[:2]}/{sha256}.jpg`,
content-addressed so dedup is free. `[Q6]` MinIO instead if S3 semantics are wanted later — default: filesystem.

### 13.2 Config

All via env, with a `.env.example`:
```
TZ=America/Los_Angeles
DATABASE_URL=postgresql+asyncpg://...
MEDIA_ROOT=/data/media
LLM_VISION_BASE_URL=http://llm-vision:8081/v1
LLM_VISION_MODEL=<model-id>
LLM_VISION_API_KEY=not-needed
LLM_TIMEOUT_S=120
LLM_MAX_RETRIES=1
VAPID_PUBLIC_KEY= / VAPID_PRIVATE_KEY=
SESSION_SECRET=
ADMIN_EMAIL=                 # parent-admin's Google address; read once by the auth migration
ADMIN_SESSION_HOURS=12
CHILD_SESSION_DAYS=90
COOKIE_SECURE=false
MEDIA_RETENTION_DAYS=180
GEO_RETENTION_DAYS=30
AUTO_PASS_THRESHOLD=0.85
AUTO_FAIL_THRESHOLD=0.35
MISS_SETTLE_DELAY_S=21600
APPEAL_WINDOW_S=259200
ENVIRONMENT=dev              # prod turns on HSTS and turns off /docs
LOG_FORMAT=json
PUBLIC_BASE_URL=http://localhost:8088
# Internet exposure (§12.2) — used by docker-compose.tunnel.yml
CLOUDFLARE_TUNNEL_TOKEN=
ALLOWED_HOSTS=               # empty disables the Host check
TRUST_PROXY_HEADERS=false
CF_ACCESS_TEAM_DOMAIN=       # e.g. yourteam.cloudflareaccess.com
CF_ACCESS_AUD=               # comma-separated, one AUD tag per Access application
```

### 13.3 Dev ergonomics

`justfile` targets: `up`, `down`, `logs`, `migrate`, `seed`, `test`, `eval`, `backup`, `restore`, `fmt`, `lint`.
Seed data MUST create two children, the four example chores from the original brief, and 30 days of
backdated occurrences in mixed states so the UI is never empty during development.

---

## 14. Implementation plan

Each phase is independently demoable. Do not start a phase before its predecessor's acceptance criteria pass.

### Phase 0 — VLM bake-off (do this first, half a day)
Standalone script, no app code. Collect ~40 real photos (20 clean sink / 20 dirty, 15 clean room / 15 messy),
label them, run 3–4 candidate vision models through the §7.3 prompt, report accuracy, mean latency, and
confidence calibration per model.
**Accept when:** a model + prompt combination is chosen with documented precision/recall, or the
decision is made to launch in `llm_assist` mode. Latency < 30s per image on the target hardware.

### Phase 1 — Core skeleton
Postgres schema + Alembic migrations, FastAPI app, auth (local accounts + TOTP), users/children CRUD,
Docker Compose, justfile, seed script, CI running lint + tests.
**Accept when:** admin and two child accounts can log in; `just up && just seed && just test` is green from a clean clone.

### Phase 2 — Chores & scheduler
Chore CRUD with the full field set, cadence parser, rotation resolver, occurrence generator, missed-detection
ticker, preview endpoint.
**Accept when:** the four brief chores are configurable through the API; a two-week horizon generates
correct occurrences including biweekly rotation; DST-crossing and month-boundary cases have unit tests;
running the generator twice creates zero duplicates.

### Phase 3 — Submissions & manual verification
Multipart upload, image pipeline (EXIF, orientation, resize, sha256, pHash), media serving with signed URLs,
admin review UI, decision endpoint, ledger writes, balances, payouts.
**Accept when:** the whole loop works end to end with `verification_mode: manual` — a photo submitted from
a phone appears in the admin inbox, approving it credits the correct amount exactly once, and a
double-submitted approve does not double-pay.

### Phase 4 — LLM verification
Job queue, verification worker, prompt builder from checklists, JSON-schema parsing with repair retry,
confidence banding, anti-cheat flags (pHash dedup, EXIF staleness, screenshot heuristics, gallery-upload),
`/health/llm`, `just eval` harness against the Phase 0 labeled set.
**Accept when:** an auto-verified pass and an auto-verified fail both work end to end; killing the LLM
container routes new submissions to `NEEDS_REVIEW` with an error note and zero incorrect ledger entries;
a resubmitted identical photo is flagged.

### Phase 5 — Kid PWA
Kid shell, in-app `getUserMedia` capture with labeled slots, offline queue, location check-in with geofence
math, `/checkin/{token}` webhook, Web Push for both roles, balance/statement views.
**Accept when:** installable and verified on **one iPhone and one Android** — capture, install-to-home-screen,
Web Push delivery, and camera permission recovery tested separately on each; a full chore completes from
lock screen to verdict in under 60 seconds; a submission made in airplane mode uploads on reconnect;
both the Shortcuts and Tasker/MacroDroid/HA check-in automations fire against the webhook successfully.
Note: iOS delivers Web Push **only** to a PWA added to the Home Screen — the onboarding flow must walk
each kid through installing it, and must detect and warn when running in a plain browser tab.

### Phase 6 — Hardening & operations
Remote access wiring, security headers/CSP, rate limits, retention jobs, backup + **tested restore**,
`/admin/jobs` dashboard, structured logging, alert on scheduler-not-ticking.
**Accept when:** a restore from last night's backup into a clean environment reproduces all balances
exactly; an external security scan shows no unauthenticated endpoint other than `/health` and
`/checkin/{token}`, and `/api/v1/auth/login` answers 404 through the tunnel (§12.1 break-glass).

### Phase 7 — Nice-to-haves (backlog)
Streaks and bonus multipliers; sibling leaderboard `[Q1]`; chore trading between kids with parent approval;
weekly email/Push digest; savings goals; recurring auto-payout on Sundays.

---

## 15. Open questions

| # | Question | Default if unanswered |
|---|---|---|
| Q1 | Can kids see each other's balances and completion rates? | No. Own data only. |
| Q2 | Photo retention period, and delete-or-thumbnail after? | 180 days, then keep a 256px thumbnail + verdict, delete the original. |
| Q3 | Can a balance go negative from penalties? | Yes, allow negative. |
| Q4 | Kid password reset flow? | Admin resets from panel. |
| ~~Q5~~ | ~~Remote access?~~ | **RESOLVED: Cloudflare Tunnel** + Access (Google) on the whole hostname; operator surfaces are LAN-only. §12.2. |
| Q6 | Filesystem media storage or MinIO? | Filesystem, content-addressed. |
| ~~Q13~~ | ~~Device mix?~~ | **RESOLVED: mixed iOS + Android.** Both geofence automation paths required (§6.2); Web Push must be verified on both; iOS requires Home Screen install before push works at all. |
| ~~Q14~~ | ~~Anti-cheat strictness?~~ | **RESOLVED: strict.** In-app `getUserMedia` only, pHash dedup, gallery uploads forced to review; EXIF/screenshot flags apply to gallery uploads only, and the prompt token was removed. §6.1. |
| Q7 | Ages of the daughters? | Drives reading level of kid-facing copy and how much friction is acceptable. Assumed 10–15. |
| Q8 | Do kids get read-only visibility into the chore *definitions* (rules, amounts)? | Yes — transparency reduces arguments. |
| Q9 | Is there an existing Postgres instance on the LAN to reuse, or run a dedicated one? | Dedicated container. |
| Q10 | Should missed chores notify the parent immediately or only in the 8:05 digest? | Digest, except for the school check-in which notifies immediately. |
| Q11 | Weekly payout cadence and method (cash, transfer, gift card)? | Manual payout entry, method free-text. |
| Q12 | Should `anyone`-mode chores exist in v1, or is every chore explicitly assigned? | Support the field, but only `fixed`/`rotating` in the v1 UI. |
| Q15 | `geofence.arrive_before` is specified but `evaluate_checkin` never reads it — flag a late check-in, fail it, or drop the field? | Not enforced in v1, and **not shown in the admin form** — a control that does nothing is worse than no control. Implement the check before surfacing it. |
| Q16 | `late_multiplier` is specified but `was_late` is never set to `True`, so it is inert. Should a late-but-in-grace submission pay less? | Not enforced in v1, not shown in the form. Enabling it means setting `was_late` in `ingest_submission` first. |

---

## 16. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| No local VLM is accurate enough for "is this room clean" | Medium-high | Phase 0 gate; `llm_assist` fallback keeps the product useful |
| Kids find the app annoying and stop using it | High | Sub-60-second happy path, useful failure messages, no confidence numbers, fast verdicts |
| Photo verification becomes a source of family conflict | Medium | Parent override always visible; model framed as "a helper that checks," never as the authority |
| Home hosting downtime causes false "missed" marks | Medium | Grace periods; admin bulk-excuse; startup reconciliation flags occurrences that expired during a known outage window |
| Internet-exposed app gets probed | Certain | Tunnel over port-forward, Cloudflare Access (Google) in front of every path but two, strict CSP, rate limits, no default credentials |
| Scope creep into a gamified allowance platform | High | Phase 7 is a backlog, not a plan. Tiered outcomes are bounded by §4.6 `[D]`: parent-authored consequences, no score, streak, badge or leaderboard |
