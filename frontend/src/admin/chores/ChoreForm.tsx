// Composition only: the fieldsets in the order a parent thinks about them. All state and
// cross-field normalisation lives in useChoreForm; each section is a pure view of it.
//
// What shows when (K = chore kind, P = proof type, V = verification mode, T = has tiers):
//
//   Identity   title, description            always; kind on create only (it is immutable)
//   Who        assignment + assignees        always; standing hides rotating/anyone
//   When       cadence or one-off date,      K=scheduled only
//              due time, opens, start,
//              grace + end date (Advanced)
//   Proof      proof type, photos, fence     K=scheduled; photo fields need P photo-bearing,
//                                            fence needs P location-bearing
//   Checking   rule, checklist, thresholds   V is an LLM mode — nothing else reads them
//   Worth      outcome tiers                 always; text-only when K=standing
//              reward / penalty              only when there are no tiers
//
// The buttons act on this chore: Save, Deactivate/Reactivate, and Duplicate.
//
// Flipping a standing chore on/off is NOT here — that is an operational act, so it lives in
// the review inbox (admin/StandingDetail.tsx) alongside everything else a parent acts on.
//
// Deliberately absent: late_multiplier and geofence.arrive_before are specified but not
// enforced anywhere (spec §15 Q15, Q16), so there is no control for them.

import type { Chore } from '../../api/types';
import { useChildren } from '../api';
import { Button, Card } from '../../shared/ui';
import { useChoreForm, type FormState } from './useChoreForm';
import { IdentitySection } from './sections/IdentitySection';
import { WhoSection } from './sections/WhoSection';
import { WhenSection } from './sections/WhenSection';
import { ProofSection } from './sections/ProofSection';
import { CheckingSection } from './sections/CheckingSection';
import { WorthSection } from './sections/WorthSection';
import { isStanding } from './choreFields';

export function ChoreForm({
  state,
  onDone,
  onDuplicated,
}: {
  state: FormState;
  onDone: () => void;
  onDuplicated?: (copy: Chore) => void;
}) {
  const kids = useChildren();
  const f = useChoreForm(state, onDone, onDuplicated);
  const kidOpts = kids.data ?? [];
  const standing = isStanding(f.form);

  return (
    <Card className="flex flex-col gap-2">
      <h2 className="font-bold">{f.editing ? `Edit — ${String(f.form.title)}` : 'New chore'}</h2>

      <IdentitySection f={f} />
      <WhoSection f={f} kids={kidOpts} />
      {!standing && (
        <>
          <WhenSection f={f} />
          <ProofSection f={f} />
          <CheckingSection f={f} />
        </>
      )}
      <WorthSection f={f} />
      {standing && f.editing && (
        <p className="text-xs text-slate-500">Turn this on or off from the review inbox.</p>
      )}

      {f.editing && (
        <p className="text-xs text-slate-500">
          Saving regenerates upcoming occurrences; completed ones are left alone.
        </p>
      )}

      {f.error && <p className="text-sm text-rose-400">{f.error}</p>}

      <div className="flex flex-wrap gap-2">
        {!standing && (
          <Button className="min-h-0 px-3 py-2 text-sm" variant="ghost" onClick={f.doPreview}>
            Preview
          </Button>
        )}
        <Button
          className="min-h-0 px-3 py-2 text-sm"
          onClick={f.save}
          disabled={f.update.isPending}
        >
          Save
        </Button>
        {f.editing && f.chore!.active && (
          <Button
            className="min-h-0 px-3 py-2 text-sm"
            variant="danger"
            onClick={f.remove}
            disabled={f.deactivate.isPending}
          >
            Deactivate
          </Button>
        )}
        {f.editing && !f.chore!.active && (
          <Button className="min-h-0 px-3 py-2 text-sm" variant="ghost" onClick={f.reactivate}>
            Reactivate
          </Button>
        )}
        {/* Duplicating belongs with the other things done *to* this chore, not on a list row
            where it competed with opening the editor. It is also how you get a chore of the
            other kind, since kind is immutable after save (IdentitySection). */}
        {f.editing && (
          <Button
            className="min-h-0 px-3 py-2 text-sm"
            variant="ghost"
            onClick={f.duplicateChore}
            disabled={f.duplicate.isPending}
          >
            Duplicate
          </Button>
        )}
        <Button className="min-h-0 px-3 py-2 text-sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>

      {f.preview && (
        <div className="mt-2 text-xs text-slate-400">
          <p className="font-semibold text-slate-300">Next occurrences</p>
          {f.preview.map((p) => (
            <p key={p.due_at}>
              {new Date(p.window_open_at).toLocaleString()} → {new Date(p.due_at).toLocaleString()}{' '}
              ·{' '}
              {kidOpts.find((k) => k.id === p.assignee_id)?.display_name ??
                p.assignee_id ??
                'anyone'}
            </p>
          ))}
        </div>
      )}
    </Card>
  );
}
