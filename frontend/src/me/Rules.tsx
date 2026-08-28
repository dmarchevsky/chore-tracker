import { useChores } from '../api/hooks';
import { Card, Spinner } from '../shared/ui';
import { money } from '../shared/format';

// Read-only visibility into the chore definitions — transparency reduces arguments
// (spec §15 Q8).
export function Rules() {
  const chores = useChores();
  if (chores.isLoading) return <Spinner />;

  return (
    <div className="flex flex-col gap-3 pt-2">
      <h1 className="text-xl font-bold">The rules</h1>
      {(chores.data ?? []).map((c) => (
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
          {c.photo_prompts?.length > 0 && (
            <p className="mt-1 text-xs text-slate-500">Photos: {c.photo_prompts.join(', ')}</p>
          )}
        </Card>
      ))}
    </div>
  );
}
