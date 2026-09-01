import type { Chore, Occurrence } from '../api/types';
import { Card } from '../shared/ui';
import { StatusBadge } from '../shared/StatusBadge';
import { occurrenceWorth } from '../shared/outcome';

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
            {subtitle}
            {occurrenceWorth(o) && ` · ${occurrenceWorth(o)}`}
          </p>
        </div>
        <StatusBadge status={o.status} role="kid" className="text-sm" />
      </div>
    </Card>
  );
}
