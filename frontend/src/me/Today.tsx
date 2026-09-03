import { Link } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { useChores, useLedger, useOccurrences } from '../api/hooks';
import type { Occurrence } from '../api/types';
import { Spinner } from '../shared/ui';
import { dueLabel } from '../shared/format';
import { firstPerKey } from '../shared/occurrences';
import { OccRow } from './occRow';
import { chargedPenalties } from './penalties';
import { PenaltyRow } from './penaltyRow';

// Chores the kid still has to act on right now.
const DO_NOW = new Set(['open', 'verified_fail']);

/** A timestamp as a clock reading — and the weekday too, when it isn't today. */
function whenLabel(iso: string, withWeekday = false): string {
  return new Date(iso).toLocaleString([], {
    ...(withWeekday ? { weekday: 'short' as const } : {}),
    hour: 'numeric',
    minute: '2-digit',
  });
}

/** Midnight-to-midnight around `now`, in the device's own timezone — the kid's "today". */
function todaySpan(now = new Date()) {
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  const end = new Date(start);
  end.setDate(end.getDate() + 1);
  return { from: start.toISOString(), to: end.toISOString() };
}

export function Today() {
  const { me } = useAuth();
  const open = useOccurrences({ status: 'open' });
  const redo = useOccurrences({ status: 'verified_fail' });
  const later = useOccurrences({ status: 'pending' });
  // A miss is still today's news: the kid can open it, read why, and dispute it while the
  // appeal window is open (spec §4.2), so it belongs on the screen they actually look at.
  const missed = useOccurrences({ status: 'missed', ...todaySpan() });
  const chores = useChores();
  // Penalties a parent charged today (spec §4.8). They cost real money and nothing else on
  // this screen mentions them — without this the first the kid hears of one is the balance.
  const ledger = useLedger(me?.id ?? '');

  if (open.isLoading || redo.isLoading || later.isLoading || missed.isLoading) return <Spinner />;
  if (open.error) return <p className="text-rose-400">Couldn’t load your chores.</p>;

  const byId = new Map((chores.data ?? []).map((c) => [c.id, c]));
  const byDue = (a: Occurrence, b: Occurrence) => +new Date(a.due_at) - +new Date(b.due_at);
  const span = todaySpan();
  const penalties = chargedPenalties(ledger.data, {
    since: new Date(span.from),
    until: new Date(span.to),
  });

  const doNow = [...(open.data ?? []), ...(redo.data ?? [])]
    .filter((o) => DO_NOW.has(o.status))
    .sort(byDue);
  const missedToday = (missed.data ?? []).sort(byDue);
  // A daily chore materialises a row per day across the horizon; a kid only
  // needs to know which one is next.
  const upcoming = (later.data ?? []).sort(byDue).filter(firstPerKey((o) => o.chore_id));

  return (
    <div className="flex flex-col gap-3 pt-2">
      <h1 className="text-xl font-bold">Today</h1>

      {doNow.length === 0 && missedToday.length === 0 && (
        // A charge is bad news sitting right below; don't cheer over it.
        <p className="text-slate-500">
          {penalties.length > 0 ? 'Nothing left to do today.' : 'Nothing to do right now. 🎉'}
        </p>
      )}
      {doNow.map((o) => (
        <Link key={o.id} to={`/me/chores/${o.id}`}>
          <OccRow
            o={o}
            chore={byId.get(o.chore_id)}
            subtitle={`${dueLabel(o.due_at)} · due ${whenLabel(o.due_at)}`}
          />
        </Link>
      ))}

      {missedToday.length > 0 && (
        <>
          <h2 className="mt-4 text-sm font-semibold text-slate-400">Missed today</h2>
          {missedToday.map((o) => (
            <Link key={o.id} to={`/me/chores/${o.id}`}>
              <OccRow
                o={o}
                chore={byId.get(o.chore_id)}
                subtitle={`was due ${whenLabel(o.due_at)}`}
              />
            </Link>
          ))}
        </>
      )}

      {penalties.length > 0 && (
        <>
          <h2 className="mt-4 text-sm font-semibold text-slate-400">Penalties</h2>
          {penalties.map((e) => (
            <PenaltyRow key={e.id} entry={e} when={whenLabel(e.created_at)} />
          ))}
        </>
      )}

      {upcoming.length > 0 && (
        <>
          <h2 className="mt-4 text-sm font-semibold text-slate-400">Coming up</h2>
          {upcoming.map((o) => (
            <OccRow
              key={o.id}
              o={o}
              chore={byId.get(o.chore_id)}
              subtitle={`opens ${whenLabel(o.window_open_at, true)} · due ${whenLabel(
                o.due_at,
                true,
              )}`}
              muted
            />
          ))}
        </>
      )}
    </div>
  );
}
