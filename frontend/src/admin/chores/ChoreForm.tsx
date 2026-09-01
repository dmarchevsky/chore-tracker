// Composition only: the fieldsets in the order a parent thinks about them. All state and
// cross-field normalisation lives in useChoreForm; each section is a pure view of it.

import { useChildren } from '../api';
import { Button, Card } from '../../shared/ui';
import { useChoreForm, type FormState } from './useChoreForm';
import { IdentitySection } from './sections/IdentitySection';
import { WhoSection } from './sections/WhoSection';
import { WhenSection } from './sections/WhenSection';
import { ProofSection } from './sections/ProofSection';
import { CheckingSection } from './sections/CheckingSection';
import { WorthSection } from './sections/WorthSection';
import { StandingSection } from './sections/StandingSection';
import { isStanding } from './choreFields';

export function ChoreForm({ state, onDone }: { state: FormState; onDone: () => void }) {
  const kids = useChildren();
  const f = useChoreForm(state, onDone);
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
      <StandingSection f={f} />

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
