import type { ReactNode } from 'react';
import type { Chore, Occurrence } from '../api/types';
import { Card } from '../shared/ui';
import { money } from '../shared/format';

// One friendly label per status, from a kid's point of view.
function statusChip(s: string): ReactNode {
  switch (s) {
    case 'open':
    case 'verified_fail':
      return <span className="text-sky-400">Do it</span>;
    case 'pending':
      return <span className="text-slate-500">Later</span>;
    case 'submitted':
    case 'needs_review':
      return <span className="text-amber-400">Waiting</span>;
    case 'verified_pass':
    case 'approved':
      return <span className="text-emerald-400">Done ✅</span>;
    case 'missed':
    case 'rejected':
      return <span className="text-rose-400">Missed</span>;
    case 'excused':
      return <span className="text-slate-400">Excused</span>;
    default:
      return <span className="text-slate-500">{s}</span>;
  }
}

export function OccRow({
  o,
  chore,
  subtitle,
  muted,
}: {
  o: Occurrence;
  chore: Chore | undefined;
  subtitle: string;
  muted?: boolean;
}) {
  return (
    <Card className={muted ? 'opacity-60' : o.status === 'open' ? 'border-sky-700' : ''}>
      <div className="flex items-center justify-between">
        <div>
          <p className="text-base font-semibold">{chore?.title ?? 'Chore'}</p>
          <p className="text-sm text-slate-400">
            {subtitle} · {money(o.reward_cents)}
          </p>
        </div>
        <div className="text-sm font-semibold">{statusChip(o.status)}</div>
      </div>
    </Card>
  );
}
