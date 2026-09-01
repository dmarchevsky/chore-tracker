import { ChecklistField, type ChecklistItem } from '../../ChecklistField';
import { LLM_MODES } from '../choreFields';
import type { ChoreFormApi } from '../useChoreForm';

export function CheckingSection({ f }: { f: ChoreFormApi }) {
  const form = f.form;
  // Only the vision worker reads the checklist and the thresholds (app/worker/verify.py).
  // Under manual or auto_accept they are dead config, so showing them would offer the
  // parent a control that does nothing.
  if (!LLM_MODES.has(String(form.verification_mode))) return null;

  return (
    <ChecklistField
      value={(form.verification_checklist as ChecklistItem[] | null) ?? null}
      onChange={(items) => f.set('verification_checklist', items)}
    />
  );
}
