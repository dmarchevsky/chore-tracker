import { Link } from 'react-router-dom';
import { useOccurrences, useChores } from '../api/hooks';
import type { Occurrence } from '../api/types';
import { Card, Spinner } from '../shared/ui';
import { dueLabel, money } from '../shared/format';

const ACTIONABLE = new Set(['open', 'needs_review', 'verified_fail']);
const DONE = new Set(['verified_pass', 'approved']);

function statusChip(s: string) {
  if (ACTIONABLE.has(s)) return <span className="text-sky-400">Do it</span>;
  if (DONE.has(s)) return <span className="text-emerald-400">Done ✅</span>;
  if (s === 'submitted' || s === 'needs_review')
    return <span className="text-amber-400">Waiting</span>;
  if (s === 'missed' || s === 'rejected') return <span className="text-rose-400">Missed</span>;
  return <span className="text-slate-500">{s}</span>;
}

export function ChoreList({
  scope,
  title,
}: {
  scope: 'today' | 'week' | 'history';
  title: string;
}) {
  const occ = useOccurrences();
  const chores = useChores();

  if (occ.isLoading || chores.isLoading) return <Spinner />;
  if (occ.error) return <p className="text-rose-400">Couldn’t load your chores.</p>;

  const byId = new Map((chores.data ?? []).map((c) => [c.id, c]));
  const now = new Date();
  const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const endOfDay = new Date(startOfDay.getTime() + 864e5);
  const endOfWeek = new Date(startOfDay.getTime() + 7 * 864e5);

  const list = (occ.data ?? [])
    .filter((o) => {
      const d = new Date(o.due_at);
      if (scope === 'today') return d < endOfDay;
      if (scope === 'week') return d >= startOfDay && d < endOfWeek;
      return d < startOfDay; // history
    })
    .sort((a, b) => +new Date(a.due_at) - +new Date(b.due_at));

  return (
    <div className="flex flex-col gap-3 pt-2">
      <h1 className="text-xl font-bold">{title}</h1>
      {list.length === 0 && <p className="text-slate-500">Nothing here. 🎉</p>}
      {list.map((o) => (
        <Row key={o.id} o={o} chore={byId.get(o.chore_id)} />
      ))}
    </div>
  );
}

function Row({ o, chore }: { o: Occurrence; chore: { title: string } | undefined }) {
  const actionable = ACTIONABLE.has(o.status);
  return (
    <Link to={`/me/chores/${o.id}`}>
      <Card className={actionable ? 'border-sky-700' : ''}>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-base font-semibold">{chore?.title ?? 'Chore'}</p>
            <p className="text-sm text-slate-400">
              {dueLabel(o.due_at)} · {money(o.reward_cents)}
            </p>
          </div>
          <div className="text-sm font-semibold">{statusChip(o.status)}</div>
        </div>
      </Card>
    </Link>
  );
}
