import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { useChores, useLedger, useOccurrences } from '../api/hooks';
import { Spinner } from '../shared/ui';
import { OccRow } from './occRow';
import { chargedPenalties } from './penalties';
import { PenaltyRow } from './penaltyRow';

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

export function History() {
  const { me } = useAuth();
  // Compute once per mount — a value that changes every render churns the query key
  // and the request never settles (perpetual spinner).
  const from = useMemo(() => new Date(Date.now() - SIXTY_DAYS_MS).toISOString(), []);
  const occ = useOccurrences({ from, order: 'desc', limit: 200 });
  const chores = useChores();
  // Charged penalties are part of the record too — a kid looking back at a bad week should
  // find them here and not only as a line on the statement (spec §4.8).
  const ledger = useLedger(me?.id ?? '');

  if (occ.isLoading) return <Spinner />;
  if (occ.error) return <p className="text-rose-400">Couldn’t load your chores.</p>;

  const byId = new Map((chores.data ?? []).map((c) => [c.id, c]));
  const list = (occ.data ?? []).filter((o) => DONE.has(o.status));
  const penalties = chargedPenalties(ledger.data, { since: new Date(from) });

  return (
    <div className="flex flex-col gap-3 pt-2">
      <h1 className="text-xl font-bold">History</h1>
      {list.length === 0 && penalties.length === 0 && (
        <p className="text-slate-500">Nothing finished yet.</p>
      )}
      {/* Only worth naming the chore list when something else follows it. */}
      {list.length > 0 && penalties.length > 0 && (
        <h2 className="text-sm font-semibold text-slate-400">Chores</h2>
      )}
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

      {penalties.length > 0 && (
        <>
          <h2 className="mt-4 text-sm font-semibold text-slate-400">Penalties</h2>
          {penalties.map((e) => (
            <PenaltyRow
              key={e.id}
              entry={e}
              when={new Date(e.created_at).toLocaleDateString([], {
                month: 'short',
                day: 'numeric',
              })}
            />
          ))}
        </>
      )}
    </div>
  );
}
