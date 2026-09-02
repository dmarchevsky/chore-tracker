// Charging a penalty rule (spec §4.8). Sits under the rule's form in the chores pane: the
// rule is what you are looking at, and applying it is the one thing you do *to* it.
//
// Two guards, both deliberate. The kid list is limited to who the rule targets, because the
// backend rejects anyone else (services/penalties.py) and offering a name that 409s is worse
// than not offering it. And nothing is charged until a second tap confirms — every other
// money-moving control in the admin sits behind a review screen, and this one does not.
import { useState } from 'react';
import { useApplyPenalty, useChildren } from '../api';
import type { Chore } from '../../api/types';
import { isAssignedTo } from '../../shared/assignment';
import { money } from '../../shared/format';
import { Button, Card, Field } from '../../shared/ui';

export function PenaltyApply({ chore }: { chore: Chore }) {
  const kids = useChildren();
  const apply = useApplyPenalty();
  const [childId, setChildId] = useState('');
  const [tierId, setTierId] = useState<number | null>(null);
  const [override, setOverride] = useState('');
  const [note, setNote] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const targets = (kids.data ?? []).filter((k) => isAssignedTo(chore, k.id));
  const tiers = chore.outcome_tiers ?? [];
  const tier = tiers.find((t) => t.id === tierId) ?? null;
  // The parent types a positive amount; the sign is the backend's to apply.
  const overrideCents = override.trim() ? Math.round(Math.abs(parseFloat(override)) * 100) : null;
  const cents = overrideCents ?? Math.abs(tier?.amount_cents ?? 0);
  const ready = Boolean(childId && tier && cents);

  if (!chore.active)
    return (
      <Card>
        <p className="text-sm text-slate-500">
          This rule is deactivated, so it can’t be charged. Reactivate it first.
        </p>
      </Card>
    );

  function reset() {
    setConfirming(false);
    setTierId(null);
    setOverride('');
    setNote('');
  }

  function charge() {
    setError(null);
    apply.mutate(
      {
        chore_id: chore.id,
        child_id: childId,
        tier_id: tier!.id,
        ...(overrideCents ? { amount_override_cents: overrideCents } : {}),
        ...(note.trim() ? { note: note.trim() } : {}),
      },
      {
        onSuccess: (entry) => {
          const who = targets.find((k) => k.id === childId)?.display_name ?? 'them';
          setDone(`Charged ${who} ${money(entry.amount_cents)}.`);
          reset();
        },
        onError: (e) => setError((e as Error).message),
      },
    );
  }

  return (
    <Card className="flex flex-col gap-2">
      <h2 className="font-bold">Charge this</h2>

      {targets.length === 0 ? (
        <p className="text-sm text-amber-400">
          Nobody is assigned to this rule yet, so there’s nobody to charge.
        </p>
      ) : (
        <>
          <Field label="Who">
            <select
              className="inp"
              value={childId}
              onChange={(e) => {
                setChildId(e.target.value);
                setConfirming(false);
              }}
            >
              <option value="">— pick a kid —</option>
              {targets.map((k) => (
                <option key={k.id} value={k.id}>
                  {k.display_name}
                </option>
              ))}
            </select>
          </Field>

          <Field label="What happened">
            <div className="flex flex-col gap-1 text-sm">
              {tiers.map((t) => (
                <label key={t.id} className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="penalty-tier"
                    // Field wraps the whole group in one <label>, so without this every
                    // radio answers to the same name — its own condition is the point.
                    aria-label={t.condition}
                    checked={tierId === t.id}
                    onChange={() => {
                      setTierId(t.id);
                      setConfirming(false);
                    }}
                  />
                  <span>{t.condition}</span>
                  <span className="text-rose-400">{money(t.amount_cents ?? 0)}</span>
                </label>
              ))}
            </div>
          </Field>

          <Field label="Different amount this time ($, optional)">
            <input
              className="inp"
              type="number"
              min="0"
              step="0.01"
              placeholder={tier ? String(Math.abs(tier.amount_cents ?? 0) / 100) : ''}
              value={override}
              onChange={(e) => {
                setOverride(e.target.value);
                setConfirming(false);
              }}
            />
          </Field>

          <Field label="Note (optional)">
            <input
              className="inp"
              placeholder="Why? Your kid reads this."
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </Field>

          {error && <p className="text-sm text-rose-400">{error}</p>}
          {done && <p className="text-sm text-emerald-400">{done}</p>}

          {confirming ? (
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm text-slate-300">
                Take <span className="text-rose-400">{money(-cents)}</span> off{' '}
                {targets.find((k) => k.id === childId)?.display_name}?
              </p>
              <Button
                className="min-h-0 px-3 py-2 text-sm"
                variant="danger"
                onClick={charge}
                disabled={apply.isPending}
              >
                Yes, charge it
              </Button>
              <Button
                className="min-h-0 px-3 py-2 text-sm"
                variant="ghost"
                onClick={() => setConfirming(false)}
              >
                Cancel
              </Button>
            </div>
          ) : (
            <Button
              className="min-h-0 self-start px-3 py-2 text-sm"
              onClick={() => {
                setDone(null);
                setConfirming(true);
              }}
              disabled={!ready}
            >
              Charge…
            </Button>
          )}
        </>
      )}
    </Card>
  );
}
