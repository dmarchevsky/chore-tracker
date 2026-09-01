import { useState } from 'react';
import { useAdminChores } from './api';
import { Button, Card, Spinner } from '../shared/ui';
import { money } from '../shared/format';
import { ChoreForm } from './chores/ChoreForm';
import type { FormState } from './chores/useChoreForm';
import { choreWorth } from '../shared/outcome';

export function Chores() {
  const chores = useAdminChores();
  const [form, setForm] = useState<FormState | null>(null);

  if (chores.isLoading) return <Spinner />;

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-bold">Chores</h1>
          <Button className="min-h-0 px-3 py-1 text-sm" onClick={() => setForm({ mode: 'create' })}>
            New chore
          </Button>
        </div>
        {(chores.data ?? []).map((c) => (
          <Card
            key={c.id}
            className={`cursor-pointer ${c.active ? '' : 'opacity-50'} ${
              form?.mode === 'edit' && form.chore.id === c.id ? 'ring-1 ring-sky-500' : ''
            }`}
          >
            {/* A row does one thing: open the editor. Everything done *to* a chore —
                duplicate included — lives in the editor beside Save and Deactivate. */}
            <button
              type="button"
              className="w-full text-left"
              onClick={() => setForm({ mode: 'edit', chore: c })}
            >
              <p className="font-semibold">
                {c.title}
                {!c.active && <span className="ml-2 text-xs text-slate-500">(inactive)</span>}
              </p>
              <p className="text-xs text-slate-400">
                {c.chore_kind === 'standing'
                  ? `standing · ${c.standing_on ? 'ON' : 'off'}`
                  : `${c.proof_type} · ${c.verification_mode}`}{' '}
                · {c.assignment_mode}
                {choreWorth(c) && ` · ${choreWorth(c)}`}
                {c.penalty_cents > 0 && ` / -${money(c.penalty_cents)}`}
              </p>
            </button>
          </Card>
        ))}
      </div>

      {form && (
        <ChoreForm
          key={form.mode === 'edit' ? form.chore.id : 'new'}
          state={form}
          onDone={() => setForm(null)}
          onDuplicated={(copy) => setForm({ mode: 'edit', chore: copy })}
        />
      )}
    </div>
  );
}
