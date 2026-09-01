import { useChores } from '../api/hooks';
import type { Chore } from '../api/types';
import { Card, Spinner } from '../shared/ui';
import { money } from '../shared/format';
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

// Read-only visibility into the chore definitions — transparency reduces arguments
// (spec §15 Q8).
export function Rules() {
  const chores = useChores();
  if (chores.isLoading) return <Spinner />;

  return (
    <div className="flex flex-col gap-3 pt-2">
      <h1 className="text-xl font-bold">The rules</h1>
      {(chores.data ?? []).map((c) =>
        c.chore_kind === 'standing' ? (
          <Card key={c.id}>
            <p className="font-semibold">
              {c.title}
              <span
                className={`ml-2 text-xs ${c.standing_on ? 'text-rose-400' : 'text-slate-500'}`}
              >
                {c.standing_on ? 'on right now' : 'off'}
              </span>
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
            <p className="mt-2 text-sm">
              Worth <span className="font-semibold text-emerald-400">{money(c.reward_cents)}</span>
              {c.penalty_cents > 0 && (
                <>
                  {' '}
                  · miss it and lose{' '}
                  <span className="font-semibold text-rose-400">{money(c.penalty_cents)}</span>
                </>
              )}
            </p>
            <p className="mt-1 text-xs text-slate-500">{proofSummary(c)}</p>
            {onceDate(c.cadence) && (
              <p className="mt-1 text-xs text-slate-500">
                Just once, on {new Date(`${onceDate(c.cadence)}T00:00`).toLocaleDateString()}
              </p>
            )}
          </Card>
        ),
      )}
    </div>
  );
}
