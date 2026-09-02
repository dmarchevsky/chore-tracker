import type { LedgerEntry } from '../api/types';
import { Card } from '../shared/ui';
import { money } from '../shared/format';

/** One charge, in the kid's words. `reason` is already "<rule>: <condition> — <note>" from
 *  the backend, which is the whole story; the rule title alone would not say what happened. */
export function PenaltyRow({ entry: e, when }: { entry: LedgerEntry; when: string }) {
  return (
    <Card className="border-rose-900">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-base font-semibold">{e.chore_title ?? 'Penalty'}</p>
          <p className="text-sm text-slate-400">{e.reason || when}</p>
          {e.reason && <p className="text-xs text-slate-500">{when}</p>}
        </div>
        <span className="shrink-0 text-sm font-semibold text-rose-400">
          {money(e.amount_cents)}
        </span>
      </div>
    </Card>
  );
}
