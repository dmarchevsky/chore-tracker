// What is currently in force for this kid. A standing chore has no occurrences, so it never
// appears in a to-do list — this banner is the only place it shows up (spec §4.7).
import { useChores } from '../api/hooks';

function since(iso: string | null): string {
  if (!iso) return '';
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return ' · since today';
  if (days === 1) return ' · since yesterday';
  return ` · for ${days} days`;
}

export function StandingBanner() {
  const chores = useChores();
  const on = (chores.data ?? []).filter((c) => c.chore_kind === 'standing' && c.standing_on);
  if (!on.length) return null;

  return (
    <div className="flex flex-col gap-2">
      {on.map((c) => {
        const tier = (c.outcome_tiers ?? []).find((t) => t.id === c.standing_tier_id);
        return (
          <div
            key={c.id}
            className="rounded-xl border border-rose-800 bg-rose-950/50 p-3 text-sm"
            role="status"
          >
            <p className="font-semibold text-rose-200">{tier?.text ?? c.title}</p>
            <p className="mt-0.5 text-xs text-rose-300/80">
              {tier?.condition ?? c.title}
              {since(c.standing_since)}
            </p>
          </div>
        );
      })}
    </div>
  );
}
