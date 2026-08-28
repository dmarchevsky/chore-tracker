# Calibration harness (spec §6.3 rule 6)

Runs a labeled folder of real photos through the **current** prompt + model and reports
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
    checklists.json      # optional: {"checks": ["...", "..."], "required": [1,2]}
  room/
    pass/   *.jpg
    fail/   *.jpg
```

`sink` and `room` have built-in checklists (see `harness.DEFAULT_CHECKLISTS`); any other
chore type needs a `checklists.json`. Add ~20 pass / 20 fail per type for a stable read
(spec §14 Phase 0).

The set itself is **not** committed — these are photos of the house. Keep it on the box
that runs the model.
