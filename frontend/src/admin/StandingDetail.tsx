// Operating a standing chore: what is in force, since when, and the flip history (spec §4.7).
//
// This lives in the review inbox rather than the chore form because flipping one is a daily
// operational act, not an edit to its definition. The chore itself is read from the
// ['chores','all'] cache by id rather than passed in, so the pane repaints in place when a
// flip lands — useSetChoreState already invalidates that key.
import { useState } from 'react';
import { Button, Card } from '../shared/ui';
import { useAdminChores, useChildren, useChoreStateHistory, useSetChoreState } from './api';
import { standingEntry, TONE_CLASS } from '../shared/status';

export function StandingDetail({ id, onDone }: { id: string; onDone: () => void }) {
  const chores = useAdminChores();
  const kids = useChildren();
  const setState = useSetChoreState();
  const history = useChoreStateHistory(id);
  const [note, setNote] = useState('');

  const chore = (chores.data ?? []).find((c) => c.id === id);
  if (!chore || chore.chore_kind !== 'standing') return null;

  const tiers = chore.outcome_tiers ?? [];
  const active = tiers.find((t) => t.id === chore.standing_tier_id);
  const who =
    chore.assignment_mode === 'fixed'
      ? (kids.data ?? []).find((k) => k.id === chore.fixed_assignee_id)?.display_name
      : (kids.data ?? [])
          .filter((k) => chore.assignee_ids.includes(k.id))
          .map((k) => k.display_name)
          .join(', ');
  const state = standingEntry(chore.standing_on);

  function flip(body: { on: boolean; tier_id?: number | null }) {
    // No onSuccess close: the point of a dedicated pane is watching the state land.
    setState.mutate(
      { id, body: { ...body, note: note || null } },
      { onSuccess: () => setNote('') },
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-bold">
          {chore.title} · <span className={TONE_CLASS[state.tone]}>{state.label}</span>
        </h2>
        <p className="text-sm text-slate-400">
          {who || 'Nobody'}
          {chore.standing_on &&
            chore.standing_since &&
            ` · since ${new Date(chore.standing_since).toLocaleDateString()}`}
        </p>
      </div>

      <Card>
        {chore.standing_on ? (
          <p className="text-sm text-rose-300">{active?.text ?? '(that outcome was removed)'}</p>
        ) : (
          <p className="text-sm text-slate-400">Nothing is in force right now.</p>
        )}

        <input
          className="inp mt-3"
          placeholder="Note (optional) — what happened"
          aria-label="Flip note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />

        <div className="mt-3 flex flex-wrap gap-2">
          {tiers.map((t) => (
            <Button
              key={t.id}
              variant={chore.standing_tier_id === t.id ? 'danger' : 'ghost'}
              className="min-h-0 px-3 py-2 text-sm"
              disabled={setState.isPending}
              onClick={() => flip({ on: true, tier_id: t.id })}
            >
              {t.condition}
            </Button>
          ))}
          {chore.standing_on && (
            <Button
              className="min-h-0 px-3 py-2 text-sm"
              disabled={setState.isPending}
              onClick={() => flip({ on: false })}
            >
              Turn it off
            </Button>
          )}
        </div>
        {setState.isError && (
          <p className="mt-2 text-sm text-rose-400">Couldn’t change that just now.</p>
        )}
      </Card>

      <Card>
        <h3 className="text-sm font-semibold text-slate-300">History</h3>
        <ul className="mt-2 flex flex-col gap-1 text-xs text-slate-500">
          {(history.data ?? []).map((e) => (
            <li key={e.id}>
              {new Date(e.created_at).toLocaleString()} — {e.state ? 'on' : 'off'}
              {e.tier ? ` · ${e.tier.condition}` : ''}
              {e.note ? ` · “${e.note}”` : ''}
            </li>
          ))}
          {!history.data?.length && <li>No flips yet.</li>}
        </ul>
      </Card>

      <Button className="min-h-0 self-start px-3 py-2 text-sm" variant="ghost" onClick={onDone}>
        Close
      </Button>
    </div>
  );
}
