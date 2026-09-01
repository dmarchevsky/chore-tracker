// The state panel for a standing chore: what is in force, since when, and the flip history.
// Only meaningful once the chore exists, so it is edit-mode only.
import { useState } from 'react';
import { Button } from '../../../shared/ui';
import { useChoreStateHistory, useSetChoreState } from '../../api';
import type { ChoreFormApi } from '../useChoreForm';
import type { OutcomeTier } from '../../../api/types';

export function StandingSection({ f }: { f: ChoreFormApi }) {
  const chore = f.chore;
  const setState = useSetChoreState();
  const history = useChoreStateHistory(chore?.id ?? null);
  const [note, setNote] = useState('');
  const [showHistory, setShowHistory] = useState(false);

  if (!chore || chore.chore_kind !== 'standing') return null;

  const tiers = (f.form.outcome_tiers as OutcomeTier[] | null) ?? [];
  const active = tiers.find((t) => t.id === chore.standing_tier_id);

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-slate-800 p-3">
      <span className="text-sm font-semibold text-slate-300">Right now</span>

      {chore.standing_on ? (
        <p className="text-sm text-rose-300">
          On — {active?.text ?? '(outcome removed)'}
          {chore.standing_since &&
            ` · since ${new Date(chore.standing_since).toLocaleDateString()}`}
        </p>
      ) : (
        <p className="text-sm text-slate-400">Off — nothing is in force.</p>
      )}

      <input
        className="inp"
        placeholder="Note (optional) — what happened"
        aria-label="Flip note"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />

      <div className="flex flex-wrap gap-2">
        {tiers.map((t) => (
          <Button
            key={t.id}
            variant={chore.standing_tier_id === t.id ? 'danger' : 'ghost'}
            className="min-h-0 px-3 py-2 text-sm"
            disabled={setState.isPending}
            onClick={() =>
              setState.mutate(
                { id: chore.id, body: { on: true, tier_id: t.id, note: note || null } },
                { onSuccess: f.onDone },
              )
            }
          >
            {t.condition}
          </Button>
        ))}
        {chore.standing_on && (
          <Button
            className="min-h-0 px-3 py-2 text-sm"
            disabled={setState.isPending}
            onClick={() =>
              setState.mutate(
                { id: chore.id, body: { on: false, note: note || null } },
                { onSuccess: f.onDone },
              )
            }
          >
            Turn it off
          </Button>
        )}
      </div>

      <button
        type="button"
        className="self-start text-xs text-slate-400 underline"
        onClick={() => setShowHistory((v) => !v)}
      >
        {showHistory ? 'Hide history' : 'History'}
      </button>
      {showHistory && (
        <ul className="flex flex-col gap-1 text-xs text-slate-500">
          {(history.data ?? []).map((e) => (
            <li key={e.id}>
              {new Date(e.created_at).toLocaleString()} — {e.state ? 'on' : 'off'}
              {e.tier ? ` · ${e.tier.condition}` : ''}
              {e.note ? ` · “${e.note}”` : ''}
            </li>
          ))}
          {!history.data?.length && <li>No flips yet.</li>}
        </ul>
      )}
    </div>
  );
}
