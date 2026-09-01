import { Field } from '../../../shared/ui';
import type { ChoreFormApi } from '../useChoreForm';

export function IdentitySection({ f }: { f: ChoreFormApi }) {
  return (
    <>
      <Field label="Title">
        <input
          className="inp"
          value={String(f.form.title ?? '')}
          onChange={(e) => f.set('title', e.target.value)}
        />
      </Field>
      <Field label="Description">
        <input
          className="inp"
          value={String(f.form.description ?? '')}
          onChange={(e) => f.set('description', e.target.value)}
        />
      </Field>
    </>
  );
}
