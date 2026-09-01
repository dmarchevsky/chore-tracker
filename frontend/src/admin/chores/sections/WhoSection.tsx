import { Field } from '../../../shared/ui';
import type { Child } from '../../../api/types';
import type { ChoreFormApi } from '../useChoreForm';

export function WhoSection({ f, kids }: { f: ChoreFormApi; kids: Child[] }) {
  const form = f.form;
  const idsSelected = (form.assignee_ids as string[]) ?? [];

  return (
    <>
      <Field label="Assignment">
        <select
          className="inp"
          value={String(form.assignment_mode)}
          onChange={(e) => f.setAssignmentMode(e.target.value)}
        >
          <option value="fixed">fixed — one kid</option>
          <option value="rotating">rotating — take turns</option>
          <option value="all">all — everyone does it</option>
          <option value="anyone">anyone — unassigned pool</option>
        </select>
      </Field>

      {form.assignment_mode === 'anyone' && (
        <p className="text-xs text-amber-400">
          Heads up: unassigned chores don’t show in any kid’s list yet — pick fixed, rotating or all
          if a kid needs to see it.
        </p>
      )}

      {form.assignment_mode === 'fixed' && (
        <Field label="Assignee">
          <select
            className="inp"
            value={String(form.fixed_assignee_id ?? '')}
            onChange={(e) => f.set('fixed_assignee_id', e.target.value)}
          >
            <option value="">— pick a kid —</option>
            {kids.map((k) => (
              <option key={k.id} value={k.id}>
                {k.display_name}
              </option>
            ))}
          </select>
        </Field>
      )}

      {(form.assignment_mode === 'rotating' || form.assignment_mode === 'all') && (
        <Field label={form.assignment_mode === 'all' ? 'Everyone' : 'Rotation between'}>
          <div className="flex flex-wrap gap-3 text-sm">
            {kids.map((k) => (
              <label key={k.id} className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={idsSelected.includes(k.id)}
                  onChange={(e) =>
                    f.set(
                      'assignee_ids',
                      e.target.checked
                        ? [...idsSelected, k.id]
                        : idsSelected.filter((id) => id !== k.id),
                    )
                  }
                />
                {k.display_name}
              </label>
            ))}
          </div>
        </Field>
      )}

      {form.assignment_mode === 'rotating' && (
        <Field label="Rotation period / anchor">
          <div className="flex gap-2">
            <select
              className="inp"
              value={String(form.rotation_period ?? '')}
              onChange={(e) => f.set('rotation_period', e.target.value)}
            >
              <option value="weekly">weekly</option>
              <option value="biweekly">biweekly</option>
            </select>
            <input
              className="inp"
              type="date"
              value={String(form.rotation_anchor_date ?? '').slice(0, 10)}
              onChange={(e) => f.set('rotation_anchor_date', e.target.value)}
            />
          </div>
        </Field>
      )}
    </>
  );
}
