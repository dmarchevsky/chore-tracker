# Calibration harnesses (spec §6.3 rule 6)

Two of them, answering different questions.

## 1. `just eval-replay` — did *our code* change its mind?

Re-decides every stored verification using today's verdict logic and reports what would
move. Needs **no model, no GPU, no network** and takes a second; it is read-only.

```
just eval-replay                    # the configured database
just eval-replay --limit 2000 --json
just eval-replay --url postgresql+asyncpg://…   # e.g. a restored backup
```

Every verification row keeps the model's raw response, so the household's own history is a
regression set nobody had to label. Run it after any change to `verdict.py` or the prompt
plumbing — it is what catches "banding a low-confidence *no* turns 30 past auto-fails into
review items" before a kid finds out.

It compares **verdicts**, not raw outcomes: the worker maps both `retake` and
`needs_review` onto `Verdict.needs_review`, and comparing outcomes reports changes that
aren't.

## 2. `just eval` — is the *model* any good?

Runs a labelled folder of real photos through the **current** prompt + model and reports
precision / recall / accuracy and mean latency per chore type. Run it after any prompt or
threshold change — otherwise tuning is guesswork.

```
just eval                       # uses eval/labeled/, thresholds from .env
uv run python -m eval.run --dir path/to/set --auto-pass 0.9 --auto-fail 0.3
```

## Folder layout

```
eval/labeled/
  sink/
    pass/   *.jpg        # the sink was genuinely empty
    fail/   *.jpg        # dishes still in the basin
    checklists.json      # optional, see below
  room/
    pass/   *.jpg
    fail/   *.jpg
```

`sink` and `room` have built-in checklists (see `harness.DEFAULT_CHECKLISTS`); any other
chore type needs a `checklists.json`. Add ~20 pass / 20 fail per type for a stable read
(spec §14 Phase 0).

The set itself is **not** committed — these are photos of the house. Keep it on the box
that runs the model.

### checklists.json

Either the old list of questions, or the richer form that mirrors what the admin form now
writes. `expect` says which answer means the chore was done, so the question can be asked
the direct way; `ignore` names things that may be present without counting against it.

```json
{
  "checks": [
    {
      "text": "Are there dirty dishes, cups, pans or utensils in the sink basin?",
      "expect": "no",
      "ignore": ["sponge", "dish brush", "drain strainer"]
    }
  ],
  "required": [1]
}
```

Asking what is *there* beats asking the model to prove an absence, and an allowance listed
in `ignore` survives where the same words trailing the question get dropped — a 4B model
failed exactly this check while naming the sponge and the brush in its own evidence.
