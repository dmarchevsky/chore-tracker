import { Field } from '../../../shared/ui';
import { CADENCE_EXAMPLES, HOURS_BEFORE, ONCE_TODAY, onceDate, opensAt } from '../choreFields';
import type { ChoreFormApi } from '../useChoreForm';

export function WhenSection({ f }: { f: ChoreFormApi }) {
  const form = f.form;
  const once = onceDate(String(form.cadence));

  return (
    <>
      <label className="flex items-center gap-2 text-sm text-slate-300">
        <input
          type="checkbox"
          checked={once !== null}
          onChange={(e) => f.set('cadence', e.target.checked ? ONCE_TODAY() : 'daily')}
        />
        One-off — a single date
      </label>

      {once !== null ? (
        <Field label="Date">
          <input
            className="inp"
            type="date"
            value={once}
            onChange={(e) => f.set('cadence', `once(${e.target.value})`)}
          />
          {once < new Date().toISOString().slice(0, 10) && (
            <p className="mt-1 text-xs text-amber-400">
              That date has already passed — no occurrence will be created.
            </p>
          )}
          <p className="mt-1 text-xs text-slate-500">
            Runs once, at the “Due time” below, then never again.
          </p>
        </Field>
      ) : (
        <Field label="Cadence">
          <input
            className="inp"
            list="cadence-options"
            placeholder="daily"
            value={String(form.cadence)}
            onChange={(e) => f.set('cadence', e.target.value)}
          />
          <datalist id="cadence-options">
            {CADENCE_EXAMPLES.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
          <div className="mt-1 flex flex-wrap gap-1">
            {CADENCE_EXAMPLES.map((c) => (
              <button
                key={c}
                type="button"
                className={`rounded border px-2 py-0.5 text-xs ${
                  form.cadence === c
                    ? 'border-sky-500 text-sky-300'
                    : 'border-slate-700 text-slate-400'
                }`}
                onClick={() => f.set('cadence', c)}
              >
                {c}
              </button>
            ))}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            <code>daily</code>, <code>weekdays</code> (Mon–Fri), <code>weekends</code> (Sat–Sun),{' '}
            <code>weekly(on=[SAT])</code> or <code>weekly(on=[MON,WED,FRI])</code>, or{' '}
            <code>monthly(day=15)</code> (clamped to the last day of shorter months). The time of
            day comes from the “Due time” field below.
          </p>
        </Field>
      )}
      <Field label="Due time">
        <input
          className="inp"
          type="time"
          value={String(form.due_time).slice(0, 5)}
          onChange={(e) => f.set('due_time', `${e.target.value}:00`)}
        />
      </Field>
      <Field label="Opens (hours before it’s due)">
        <input
          className="inp"
          type="number"
          step="0.25"
          min="0"
          max="336"
          value={HOURS_BEFORE(Number(form.window_open_offset_s))}
          onChange={(e) =>
            f.set('window_open_offset_s', -Math.round(parseFloat(e.target.value || '0') * 3600))
          }
        />
        <p className="mt-1 text-xs text-slate-500">
          {opensAt(String(form.due_time), Number(form.window_open_offset_s))} — a kid can’t submit
          before that.
        </p>
      </Field>
      <Field label={`Start date${f.editing ? ' (fixed)' : ''}`}>
        <input
          className="inp"
          type="date"
          disabled={f.editing}
          value={String(form.start_date).slice(0, 10)}
          onChange={(e) => f.set('start_date', e.target.value)}
        />
      </Field>
    </>
  );
}
