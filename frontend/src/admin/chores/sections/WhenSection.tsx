import { DurationInput } from '../../../shared/DurationInput';
import { Field } from '../../../shared/ui';
import { CADENCE_EXAMPLES, ONCE_TODAY, onceDate, opensAt } from '../choreFields';
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
          onChange={(e) => {
            const on = e.target.checked;
            f.set('cadence', on ? ONCE_TODAY() : 'daily');
            f.set('end_date', on ? new Date().toISOString().slice(0, 10) : null);
          }}
        />
        One-off — a single date
      </label>

      {once !== null ? (
        <Field label="Date">
          <input
            className="inp"
            type="date"
            value={once}
            onChange={(e) => {
              f.set('cadence', `once(${e.target.value})`);
              f.set('end_date', e.target.value || null);
            }}
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
      <Field label="Opens (before it’s due)">
        {/* Stored as a negative offset from the due time; the box only ever sees how long
            before, which is how a parent says it. */}
        <DurationInput
          value={-Number(form.window_open_offset_s)}
          onChange={(secs) => f.set('window_open_offset_s', -secs)}
          max={14 * 24 * 3600}
        />
        <p className="mt-1 text-xs text-slate-500">
          e.g. <code>2h30m</code>, <code>90m</code>, <code>12h</code> —{' '}
          {opensAt(String(form.due_time), Number(form.window_open_offset_s))}, and a kid can’t
          submit before that.
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

      {/* Both of these are live in the backend but had no control at all: grace_period_s
          drives open_due_windows and detect_missed, end_date bounds generation. */}
      <details className="rounded-xl border border-slate-800 p-3">
        <summary className="cursor-pointer text-sm text-slate-400">Advanced</summary>
        <div className="mt-2 flex flex-col gap-2">
          <Field label="Grace period">
            <DurationInput
              value={Number(form.grace_period_s ?? 0)}
              onChange={(secs) => f.set('grace_period_s', secs)}
              max={24 * 3600}
            />
            <p className="mt-1 text-xs text-slate-500">
              How late still counts — <code>15m</code>, <code>1h30m</code>. After this it is marked
              missed.
            </p>
          </Field>
          {once === null && (
            <Field label="End date (optional)">
              <input
                className="inp"
                type="date"
                value={String(form.end_date ?? '').slice(0, 10)}
                onChange={(e) => f.set('end_date', e.target.value || null)}
              />
              <p className="mt-1 text-xs text-slate-500">Leave empty to run indefinitely.</p>
            </Field>
          )}
        </div>
      </details>
    </>
  );
}
