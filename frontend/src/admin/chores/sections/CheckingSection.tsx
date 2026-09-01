import { Field } from '../../../shared/ui';
import { ChecklistField, type ChecklistItem } from '../../ChecklistField';
import { PHOTO_PROOFS } from '../choreFields';
import type { ChoreFormApi } from '../useChoreForm';

export function CheckingSection({ f }: { f: ChoreFormApi }) {
  const form = f.form;
  if (!PHOTO_PROOFS.has(String(form.proof_type))) return null;

  return (
    <>
      <Field label="Verification rule (natural language)">
        <input
          className="inp"
          value={String(form.verification_rule ?? '')}
          onChange={(e) => f.set('verification_rule', e.target.value)}
        />
      </Field>

      <ChecklistField
        value={(form.verification_checklist as ChecklistItem[] | null) ?? null}
        onChange={(items) => f.set('verification_checklist', items)}
      />
    </>
  );
}
