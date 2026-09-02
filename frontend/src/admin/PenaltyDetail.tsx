// Charging a penalty rule from the review inbox (spec §4.8).
//
// Same reasoning as StandingDetail: charging a rule is a daily operational act, not an edit
// to its definition, so it belongs where the parent already is. The chore is read from the
// ['chores','all'] cache by id rather than passed in, so the pane repaints in place if the
// rule is edited elsewhere.
//
// The form itself is PenaltyApply, mounted verbatim — it is the same control the chore form
// offers, and two copies of a money-moving confirm flow is one too many.
import { PenaltyApply } from './chores/PenaltyApply';
import { useAdminChores, useChildren } from './api';
import { Button, Card } from '../shared/ui';

export function PenaltyDetail({ id, onDone }: { id: string; onDone: () => void }) {
  const chores = useAdminChores();
  const kids = useChildren();

  const chore = (chores.data ?? []).find((c) => c.id === id);
  if (!chore || chore.chore_kind !== 'penalty') return null;

  const who =
    chore.assignment_mode === 'fixed'
      ? (kids.data ?? []).find((k) => k.id === chore.fixed_assignee_id)?.display_name
      : (kids.data ?? [])
          .filter((k) => chore.assignee_ids.includes(k.id))
          .map((k) => k.display_name)
          .join(', ');

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-bold">{chore.title}</h2>
        <p className="text-sm text-slate-400">{who || 'Nobody'}</p>
      </div>

      {chore.description && (
        <Card>
          <p className="text-sm text-slate-300">{chore.description}</p>
        </Card>
      )}

      <PenaltyApply chore={chore} />

      <Button className="min-h-0 self-start px-3 py-2 text-sm" variant="ghost" onClick={onDone}>
        Close
      </Button>
    </div>
  );
}
