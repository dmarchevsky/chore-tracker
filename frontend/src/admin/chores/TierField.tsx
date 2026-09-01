// Repeatable condition -> outcome editor. Same contract as ChecklistField: T[] | null,
// renumbered on every mutation, collapsing back to null when the last row goes.
import type { OutcomeTier } from '../../api/types';
import { Button } from '../../shared/ui';

const MONEY_TIER: Omit<OutcomeTier, 'id'> = {
  condition: '',
  outcome_kind: 'money',
  amount_cents: 100,
  text: null,
};
const TEXT_TIER: Omit<OutcomeTier, 'id'> = {
  condition: '',
  outcome_kind: 'text',
  amount_cents: null,
  text: '',
};

/** Ids must be 1..N in order — the backend enforces it so "tier 3" means the same thing
 *  in the audit log as it does on screen. */
const renumber = (items: OutcomeTier[]): OutcomeTier[] =>
  items.map((it, i) => ({ ...it, id: i + 1 }));

export function TierField({
  value,
  onChange,
  textOnly = false,
}: {
  value: OutcomeTier[] | null;
  onChange: (v: OutcomeTier[] | null) => void;
  /** A standing chore writes no ledger entries, so its outcomes are sentences only. */
  textOnly?: boolean;
}) {
  const items = value ?? [];

  function edit(idx: number, patch: Partial<OutcomeTier>) {
    onChange(renumber(items.map((it, i) => (i === idx ? { ...it, ...patch } : it))));
  }

  function setKind(idx: number, kind: OutcomeTier['outcome_kind']) {
    // The two shapes are mutually exclusive server-side: a money tier carries no text and
    // a text tier no amount.
    edit(
      idx,
      kind === 'money'
        ? { outcome_kind: kind, amount_cents: 100, text: null }
        : { outcome_kind: kind, amount_cents: null, text: '' },
    );
  }

  function remove(idx: number) {
    const next = renumber(items.filter((_, i) => i !== idx));
    onChange(next.length ? next : null);
  }

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-slate-800 p-3">
      <span className="text-sm font-semibold text-slate-300">Outcomes</span>
      <p className="text-xs text-slate-500">
        You decide which one happened when you review it. Exactly one applies. Leave this empty for
        an ordinary chore with a single reward.
      </p>

      {items.map((it, i) => {
        const penalty = (it.amount_cents ?? 0) < 0;
        // Ring the fields the backend would reject, so "finish outcome 2" points somewhere.
        const ring = (bad: boolean) => (bad ? ' ring-1 ring-rose-500' : '');
        return (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <span className="w-4 text-xs text-slate-500">{it.id}</span>
            <input
              className={`inp min-w-[8rem] flex-1${ring(!it.condition.trim())}`}
              placeholder="all A grades"
              aria-label={`Condition ${it.id}`}
              value={it.condition}
              onChange={(e) => edit(i, { condition: e.target.value })}
            />
            <span className="text-xs text-slate-500">→</span>
            {!textOnly && (
              <select
                className="inp w-24"
                aria-label={`Outcome type ${it.id}`}
                value={it.outcome_kind}
                onChange={(e) => setKind(i, e.target.value as OutcomeTier['outcome_kind'])}
              >
                <option value="money">money</option>
                <option value="text">text</option>
              </select>
            )}

            {!textOnly && it.outcome_kind === 'money' ? (
              <>
                {/* The parent picks reward or penalty; the minus sign is ours to apply. */}
                <select
                  className="inp w-24"
                  aria-label={`Reward or penalty ${it.id}`}
                  value={penalty ? 'penalty' : 'reward'}
                  onChange={(e) =>
                    edit(i, {
                      amount_cents:
                        Math.abs(it.amount_cents ?? 0) * (e.target.value === 'penalty' ? -1 : 1),
                    })
                  }
                >
                  <option value="reward">reward</option>
                  <option value="penalty">penalty</option>
                </select>
                <input
                  className={`inp w-24${ring(!it.amount_cents)}`}
                  type="number"
                  min="0"
                  step="0.01"
                  aria-label={`Amount ${it.id}`}
                  value={Math.abs(it.amount_cents ?? 0) / 100}
                  onChange={(e) =>
                    edit(i, {
                      amount_cents:
                        Math.round(Math.abs(parseFloat(e.target.value || '0')) * 100) *
                        (penalty ? -1 : 1),
                    })
                  }
                />
              </>
            ) : (
              <input
                className={`inp min-w-[8rem] flex-1${ring(!it.text?.trim())}`}
                placeholder="grounded until it’s fixed"
                aria-label={`Outcome text ${it.id}`}
                value={it.text ?? ''}
                onChange={(e) => edit(i, { text: e.target.value })}
              />
            )}

            <button
              type="button"
              className="px-2 text-slate-500"
              aria-label={`Remove outcome ${it.id}`}
              onClick={() => remove(i)}
            >
              ✕
            </button>
          </div>
        );
      })}

      <Button
        variant="ghost"
        className="min-h-0 self-start px-3 py-1 text-xs"
        onClick={() =>
          onChange(renumber([...items, { ...(textOnly ? TEXT_TIER : MONEY_TIER), id: 0 }]))
        }
      >
        Add an outcome
      </Button>
    </div>
  );
}
