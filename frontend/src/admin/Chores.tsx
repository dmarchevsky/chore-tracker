import { useState } from 'react';
import { useAdminChores, useChildren, useDeactivateChore, useUpdateChore } from './api';
import type { ChoreApply } from './api';
import { api } from '../api/client';
import { useQueryClient } from '@tanstack/react-query';
import type { Chore } from '../api/types';
import { Button, Card, Spinner } from '../shared/ui';
import { money } from '../shared/format';

interface PreviewItem {
  due_at: string;
  window_open_at: string;
  assignee_id: string | null;
}

const BLANK: Record<string, unknown> = {
  title: '',
  description: '',
  assignment_mode: 'fixed',
  fixed_assignee_id: '',
  assignee_ids: [],
  rotation_period: 'weekly',
  rotation_anchor_date: new Date().toISOString().slice(0, 10),
  cadence: 'daily',
  due_time: '08:00:00',
  start_date: new Date().toISOString().slice(0, 10),
  proof_type: 'photo',
  photo_count: 1,
  verification_mode: 'manual',
  verification_rule: '',
  reward_cents: 100,
  penalty_cents: 0,
  auto_pass_threshold: 0.85,
  auto_fail_threshold: 0.35,
};

// Fields the backend PATCH accepts (spec §4.1 ChoreUpdate) — proof_type / start_date excluded.
const EDITABLE = [
  'title',
  'description',
  'assignment_mode',
  'fixed_assignee_id',
  'assignee_ids',
  'rotation_period',
  'rotation_anchor_date',
  'cadence',
  'due_time',
  'verification_mode',
  'verification_rule',
  'reward_cents',
  'penalty_cents',
  'auto_pass_threshold',
  'auto_fail_threshold',
] as const;

type FormState = { mode: 'create' } | { mode: 'edit'; chore: Chore };

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
                {c.proof_type} · {c.verification_mode} · {c.assignment_mode} ·{' '}
                {money(c.reward_cents)}
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
        />
      )}
    </div>
  );
}

function ChoreForm({ state, onDone }: { state: FormState; onDone: () => void }) {
  const qc = useQueryClient();
  const kids = useChildren();
  const update = useUpdateChore();
  const deactivate = useDeactivateChore();
  const chore = state.mode === 'edit' ? state.chore : null;
  const editing = chore !== null;

  const [form, setForm] = useState<Record<string, unknown>>(
    chore ? { ...(chore as unknown as Record<string, unknown>) } : { ...BLANK },
  );
  const [apply, setApply] = useState<ChoreApply>('forward');
  const [preview, setPreview] = useState<PreviewItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  function set(k: string, v: unknown) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function doPreview() {
    setError(null);
    try {
      setPreview(await api.post<PreviewItem[]>('/chores/preview?count=8', form));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function save() {
    setError(null);
    try {
      if (editing) {
        const patch: Record<string, unknown> = {};
        for (const k of EDITABLE) patch[k] = form[k];
        if (form.assignment_mode !== 'rotating') {
          delete patch.assignee_ids;
          delete patch.rotation_period;
          delete patch.rotation_anchor_date;
        }
        if (form.assignment_mode !== 'fixed') delete patch.fixed_assignee_id;
        await update.mutateAsync({ id: chore!.id, body: patch, apply });
      } else {
        await api.post('/chores', form);
        await qc.invalidateQueries({ queryKey: ['chores', 'all'] });
      }
      onDone();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function remove() {
    setError(null);
    try {
      await deactivate.mutateAsync(chore!.id);
      onDone();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const kidOpts = kids.data ?? [];
  const idsSelected = (form.assignee_ids as string[]) ?? [];

  return (
    <Card className="flex flex-col gap-2">
      <h2 className="font-bold">{editing ? `Edit — ${String(form.title)}` : 'New chore'}</h2>

      <Field label="Title">
        <input
          className="inp"
          value={String(form.title ?? '')}
          onChange={(e) => set('title', e.target.value)}
        />
      </Field>
      <Field label="Description">
        <input
          className="inp"
          value={String(form.description ?? '')}
          onChange={(e) => set('description', e.target.value)}
        />
      </Field>

      <Field label="Assignment">
        <select
          className="inp"
          value={String(form.assignment_mode)}
          onChange={(e) => set('assignment_mode', e.target.value)}
        >
          <option value="fixed">fixed</option>
          <option value="rotating">rotating</option>
        </select>
      </Field>

      {form.assignment_mode === 'fixed' && (
        <Field label="Assignee">
          <select
            className="inp"
            value={String(form.fixed_assignee_id ?? '')}
            onChange={(e) => set('fixed_assignee_id', e.target.value)}
          >
            <option value="">— pick a kid —</option>
            {kidOpts.map((k) => (
              <option key={k.id} value={k.id}>
                {k.display_name}
              </option>
            ))}
          </select>
        </Field>
      )}

      {form.assignment_mode === 'rotating' && (
        <>
          <Field label="Rotation between">
            <div className="flex flex-wrap gap-3 text-sm">
              {kidOpts.map((k) => (
                <label key={k.id} className="flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={idsSelected.includes(k.id)}
                    onChange={(e) =>
                      set(
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
          <Field label="Rotation period / anchor">
            <div className="flex gap-2">
              <select
                className="inp"
                value={String(form.rotation_period ?? 'weekly')}
                onChange={(e) => set('rotation_period', e.target.value)}
              >
                <option value="weekly">weekly</option>
                <option value="biweekly">biweekly</option>
              </select>
              <input
                className="inp"
                type="date"
                value={String(form.rotation_anchor_date ?? '').slice(0, 10)}
                onChange={(e) => set('rotation_anchor_date', e.target.value)}
              />
            </div>
          </Field>
        </>
      )}

      <Field label="Cadence">
        <input
          className="inp"
          value={String(form.cadence)}
          onChange={(e) => set('cadence', e.target.value)}
        />
      </Field>
      <Field label="Due time">
        <input
          className="inp"
          type="time"
          value={String(form.due_time).slice(0, 5)}
          onChange={(e) => set('due_time', `${e.target.value}:00`)}
        />
      </Field>
      <Field label={`Start date${editing ? ' (fixed)' : ''}`}>
        <input
          className="inp"
          type="date"
          disabled={editing}
          value={String(form.start_date).slice(0, 10)}
          onChange={(e) => set('start_date', e.target.value)}
        />
      </Field>

      <Field label="Proof / verification">
        <div className="flex gap-2">
          <select
            className="inp"
            disabled={editing}
            value={String(form.proof_type)}
            onChange={(e) => set('proof_type', e.target.value)}
          >
            <option>photo</option>
            <option value="photo+location">photo+location</option>
            <option>location</option>
            <option>acknowledgement</option>
            <option>none</option>
          </select>
          <select
            className="inp"
            value={String(form.verification_mode)}
            onChange={(e) => set('verification_mode', e.target.value)}
          >
            <option>manual</option>
            <option>llm_assist</option>
            <option>llm_auto</option>
            <option>auto_accept</option>
          </select>
        </div>
      </Field>
      <Field label="Verification rule (natural language)">
        <input
          className="inp"
          value={String(form.verification_rule ?? '')}
          onChange={(e) => set('verification_rule', e.target.value)}
        />
      </Field>

      <Field label="Reward / penalty ($)">
        <div className="flex gap-2">
          <input
            className="inp"
            type="number"
            value={Number(form.reward_cents) / 100}
            onChange={(e) =>
              set('reward_cents', Math.round(parseFloat(e.target.value || '0') * 100))
            }
          />
          <input
            className="inp"
            type="number"
            value={Number(form.penalty_cents) / 100}
            onChange={(e) =>
              set('penalty_cents', Math.round(parseFloat(e.target.value || '0') * 100))
            }
          />
        </div>
      </Field>
      <Field label="Auto pass / fail confidence">
        <div className="flex gap-2">
          <input
            className="inp"
            type="number"
            step="0.05"
            min="0"
            max="1"
            value={Number(form.auto_pass_threshold)}
            onChange={(e) => set('auto_pass_threshold', parseFloat(e.target.value || '0'))}
          />
          <input
            className="inp"
            type="number"
            step="0.05"
            min="0"
            max="1"
            value={Number(form.auto_fail_threshold)}
            onChange={(e) => set('auto_fail_threshold', parseFloat(e.target.value || '0'))}
          />
        </div>
      </Field>

      {editing && (
        <Field label="Apply changes to">
          <select
            className="inp"
            value={apply}
            onChange={(e) => setApply(e.target.value as ChoreApply)}
          >
            <option value="forward">definition only (keep generated occurrences)</option>
            <option value="future_generated">regenerate upcoming occurrences</option>
          </select>
        </Field>
      )}

      {error && <p className="text-sm text-rose-400">{error}</p>}

      <div className="flex flex-wrap gap-2">
        <Button className="min-h-0 px-3 py-2 text-sm" variant="ghost" onClick={doPreview}>
          Preview
        </Button>
        <Button className="min-h-0 px-3 py-2 text-sm" onClick={save} disabled={update.isPending}>
          Save
        </Button>
        {editing && chore!.active && (
          <Button
            className="min-h-0 px-3 py-2 text-sm"
            variant="danger"
            onClick={remove}
            disabled={deactivate.isPending}
          >
            Deactivate
          </Button>
        )}
        {editing && !chore!.active && (
          <Button
            className="min-h-0 px-3 py-2 text-sm"
            variant="ghost"
            onClick={() => {
              set('active', true);
              void update
                .mutateAsync({ id: chore!.id, body: { active: true }, apply: 'forward' })
                .then(onDone)
                .catch((e) => setError((e as Error).message));
            }}
          >
            Reactivate
          </Button>
        )}
        <Button className="min-h-0 px-3 py-2 text-sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>

      {preview && (
        <div className="mt-2 text-xs text-slate-400">
          <p className="font-semibold text-slate-300">Next occurrences</p>
          {preview.map((p) => (
            <p key={p.due_at}>
              {new Date(p.due_at).toLocaleString()} →{' '}
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

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-slate-400">{label}</span>
      {children}
    </label>
  );
}
