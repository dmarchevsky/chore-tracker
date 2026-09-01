import { Field } from '../../../shared/ui';
import type { ChoreFormApi } from '../useChoreForm';

export function IdentitySection({ f }: { f: ChoreFormApi }) {
  return (
    <>
      {/* Immutable after save: flipping kinds would strand a scheduled chore's occurrences.
          Duplicate the chore instead. */}
      {!f.editing && (
        <Field label="Kind">
          <select
            className="inp"
            value={String(f.form.chore_kind ?? 'scheduled')}
            onChange={(e) => f.setChoreKind(e.target.value)}
          >
            <option value="scheduled">scheduled — recurs on a cadence</option>
            <option value="standing">standing — a state you flip on and off</option>
          </select>
        </Field>
      )}
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
