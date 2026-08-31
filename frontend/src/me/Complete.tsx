import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useChores, useOccurrences } from '../api/hooks';
import { Spinner } from '../shared/ui';
import { OccRow } from './occRow';

// Everything that isn't still on the kid's plate.
const DONE = new Set([
  'submitted',
  'needs_review',
  'verified_pass',
  'approved',
  'rejected',
  'missed',
  'excused',
]);

const SIXTY_DAYS_MS = 60 * 864e5;

export function Complete() {
  // Compute once per mount — a value that changes every render churns the query key
  // and the request never settles (perpetual spinner).
  const from = useMemo(() => new Date(Date.now() - SIXTY_DAYS_MS).toISOString(), []);
  const occ = useOccurrences({ from, order: 'desc', limit: 200 });
  const chores = useChores();

  if (occ.isLoading) return <Spinner />;
  if (occ.error) return <p className="text-rose-400">Couldn’t load your chores.</p>;

  const byId = new Map((chores.data ?? []).map((c) => [c.id, c]));
  const list = (occ.data ?? []).filter((o) => DONE.has(o.status));

  return (
    <div className="flex flex-col gap-3 pt-2">
      <h1 className="text-xl font-bold">Done</h1>
      {list.length === 0 && <p className="text-slate-500">Nothing finished yet.</p>}
      {list.map((o) => (
        <Link key={o.id} to={`/me/chores/${o.id}`}>
          <OccRow
            o={o}
            chore={byId.get(o.chore_id)}
            subtitle={new Date(o.due_at).toLocaleDateString([], {
              month: 'short',
              day: 'numeric',
            })}
          />
        </Link>
      ))}
    </div>
  );
}
