import { Button } from '../shared/ui';

export interface ChecklistItem {
  id: number;
  text: string;
  required: boolean;
  /** Which answer means the chore was done. Lets the question be written the direct way —
   *  "Are there dirty dishes in the basin?" — instead of inverted into "is it clear of…",
   *  which is much harder for a vision model to answer. */
  expect?: 'yes' | 'no';
  /** Things that may be present without counting against the check. Sent as its own
   *  instruction line, because the same words trailing the question got dropped. */
  ignore?: string[];
}

interface Props {
  value: ChecklistItem[] | null;
  onChange: (items: ChecklistItem[] | null) => void;
}

/** Ids are renumbered 1..N on every edit so what we store is always contiguous. The
 *  worker no longer depends on that — it asks the model under the stored ids — but a
 *  tidy list is easier to read in the audit log and the raw model request. */
const renumber = (items: ChecklistItem[]): ChecklistItem[] =>
  items.map((it, i) => ({ ...it, id: i + 1 }));

export function ChecklistField({ value, onChange }: Props) {
  const items = value ?? [];

  function edit(idx: number, patch: Partial<ChecklistItem>) {
    onChange(renumber(items.map((it, i) => (i === idx ? { ...it, ...patch } : it))));
  }

  function remove(idx: number) {
    const next = renumber(items.filter((_, i) => i !== idx));
    onChange(next.length ? next : null);
  }

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-slate-800 p-3">
      <span className="text-sm font-semibold text-slate-300">Checks the AI answers</span>
      <p className="text-xs text-slate-500">
        One yes/no question per line — this is the only thing the model is asked. Each gets its own
        answer, confidence and evidence, so several small checks beat one broad one. With no checks
        here, every photo comes to you for review.
      </p>
      {items.length === 0 && (
        <p className="text-xs text-slate-500">
          None yet — the rule above is used as a single check. Atomic yes/no questions beat one
          broad rule: “are there dishes in the sink basin?” is answerable, “is the kitchen clean?”
          isn’t.
        </p>
      )}
      {items.map((it, i) => (
        <div key={i} className="flex flex-col gap-1 border-b border-slate-800 pb-2 last:border-0">
          <div className="flex items-center gap-2">
            <span className="w-4 text-xs text-slate-500">{it.id}</span>
            <input
              className="inp flex-1"
              placeholder="Are there dirty dishes in the sink basin?"
              value={it.text}
              onChange={(e) => edit(i, { text: e.target.value })}
            />
            <button
              type="button"
              aria-label={`Remove check ${it.id}`}
              className="shrink-0 px-2 text-slate-500"
              onClick={() => remove(i)}
            >
              ✕
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-3 pl-6">
            <label className="flex shrink-0 items-center gap-1 text-xs text-slate-400">
              Done when the answer is
              <select
                className="rounded-lg bg-slate-800 p-1 text-xs"
                aria-label={`Check ${it.id} passes when the answer is`}
                value={it.expect ?? 'yes'}
                onChange={(e) => edit(i, { expect: e.target.value as 'yes' | 'no' })}
              >
                <option value="yes">yes</option>
                <option value="no">no</option>
              </select>
            </label>
            <label className="flex shrink-0 items-center gap-1 text-xs text-slate-400">
              <input
                type="checkbox"
                checked={it.required}
                onChange={(e) => edit(i, { required: e.target.checked })}
              />
              must pass
            </label>
            <input
              className="inp min-w-[12rem] flex-1 text-xs"
              aria-label={`Check ${it.id} ignores`}
              placeholder="ignore, comma separated — sponge, dish brush"
              value={(it.ignore ?? []).join(', ')}
              onChange={(e) =>
                edit(i, {
                  ignore: e.target.value
                    .split(',')
                    .map((x) => x.trim())
                    .filter(Boolean),
                })
              }
            />
          </div>
        </div>
      ))}
      <div>
        <Button
          className="min-h-0 px-3 py-1 text-xs"
          variant="ghost"
          onClick={() =>
            onChange(renumber([...items, { id: items.length + 1, text: '', required: true }]))
          }
        >
          Add a check
        </Button>
      </div>
      {items.length > 0 && (
        <p className="text-xs text-slate-500">
          A “must pass” check that comes back with the wrong answer fails the chore; an optional one
          is recorded but doesn’t decide it. Ask the question the direct way — “are there dirty
          dishes in the basin?”, done when the answer is <em>no</em> — rather than inverting it into
          “is the basin clear?”. Spotting something is far easier for the model than proving its
          absence. Anything in <em>ignore</em> is named to the model as not a problem, which is much
          more reliable than putting “a sponge is fine” at the end of the question.
        </p>
      )}
    </div>
  );
}
