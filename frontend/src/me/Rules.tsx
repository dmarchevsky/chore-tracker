import { useChores } from '../api/hooks';
import { useAuth } from '../auth/AuthContext';
import { isAssignedTo, isVisibleTo } from '../shared/assignment';
import type { Chore } from '../api/types';
import { Card, Spinner } from '../shared/ui';
import { money, tierOutcome } from '../shared/format';
import { onceDate } from '../admin/chores/choreFields';

function proofSummary(c: Chore): string {
  if (c.proof_type === 'photo')
    return c.photo_prompts.length
      ? `Photo${c.photo_count > 1 ? ` ×${c.photo_count}` : ''}: ${c.photo_prompts.join(', ')}`
      : `Take ${c.photo_count > 1 ? `${c.photo_count} photos` : 'a photo'}`;
  if (c.proof_type === 'location' || c.proof_type === 'photo+location')
    return 'Check in at the place';
  return 'Just tick it off';
}

// Read-only visibility into the kid's own chore definitions — transparency reduces
// arguments (spec §15 Q8), but a sibling's chores are not their business (spec §15 Q1).
export function Rules() {
  const chores = useChores();
  const { me } = useAuth();
  if (chores.isLoading) return <Spinner />;

  const mine = (chores.data ?? []).filter((c) => isVisibleTo(c, me?.id));
  // Penalty rules get their own section rather than sitting among the chores: a chore is
  // something to go and do, a penalty rule is a price you want to know before it costs you
  // anything (spec §4.8). Same visibility rule as everything else here — a sibling's rules
  // are not this kid's business (spec §15 Q1).
  const penalties = mine.filter((c) => c.chore_kind === 'penalty');
  const todo = mine.filter((c) => c.chore_kind !== 'penalty');

  return (
    <div className="flex flex-col gap-3 pt-2">
      <h1 className="text-xl font-bold">The rules</h1>
      {todo.map((c) =>
        c.chore_kind === 'standing' ? (
          <Card key={c.id}>
            <p className="font-semibold">
              {c.title}
              {/* An `anyone` chore is in the list as a rule anybody may read, but it is
                  nobody's in particular — so it gets no live on/off state (spec §15 Q1). */}
              {isAssignedTo(c, me?.id) && (
                <span
                  className={`ml-2 text-xs ${c.standing_on ? 'text-rose-400' : 'text-slate-500'}`}
                >
                  {c.standing_on ? 'on right now' : 'off'}
                </span>
              )}
            </p>
            {c.description && <p className="mt-1 text-sm text-slate-400">{c.description}</p>}
            <ul className="mt-2 flex flex-col gap-1 text-sm text-slate-300">
              {(c.outcome_tiers ?? []).map((t) => (
                <li key={t.id}>
                  {t.condition} → <span className="text-rose-300">{t.text}</span>
                </li>
              ))}
            </ul>
          </Card>
        ) : (
          <Card key={c.id}>
            <p className="font-semibold">{c.title}</p>
            {c.description && <p className="mt-1 text-sm text-slate-400">{c.description}</p>}
            {c.outcome_tiers?.length ? (
              <ul className="mt-2 flex flex-col gap-1 text-sm">
                {c.outcome_tiers.map((t) => (
                  <li key={t.id}>
                    {t.condition} →{' '}
                    <span
                      className={`font-semibold ${
                        (t.amount_cents ?? 0) < 0 ? 'text-rose-400' : 'text-emerald-400'
                      }`}
                    >
                      {tierOutcome(t)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm">
                Worth{' '}
                <span className="font-semibold text-emerald-400">{money(c.reward_cents)}</span>
                {c.penalty_cents > 0 && (
                  <>
                    {' '}
                    · miss it and lose{' '}
                    <span className="font-semibold text-rose-400">{money(c.penalty_cents)}</span>
                  </>
                )}
              </p>
            )}
            <p className="mt-1 text-xs text-slate-500">{proofSummary(c)}</p>
            {onceDate(c.cadence) && (
              <p className="mt-1 text-xs text-slate-500">
                Just once, on {new Date(`${onceDate(c.cadence)}T00:00`).toLocaleDateString()}
              </p>
            )}
          </Card>
        ),
      )}

      {penalties.length > 0 && (
        <>
          <h2 className="mt-2 text-lg font-bold">Costs you money</h2>
          <p className="-mt-1 text-sm text-slate-400">
            If one of these happens, a parent can take the money off. You’re seeing it here first so
            it’s never a surprise.
          </p>
          {penalties.map((c) => (
            <Card key={c.id}>
              <p className="font-semibold">{c.title}</p>
              {c.description && <p className="mt-1 text-sm text-slate-400">{c.description}</p>}
              <ul className="mt-2 flex flex-col gap-1 text-sm">
                {(c.outcome_tiers ?? []).map((t) => (
                  <li key={t.id}>
                    {t.condition} →{' '}
                    <span className="font-semibold text-rose-400">
                      {money(t.amount_cents ?? 0)}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </>
      )}
    </div>
  );
}
