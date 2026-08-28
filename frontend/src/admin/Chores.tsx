import { useState } from 'react';
import { useAdminChores } from './api';
import { api } from '../api/client';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Card, Spinner } from '../shared/ui';
import { money } from '../shared/format';

interface PreviewItem {
  due_at: string;
  window_open_at: string;
  assignee_id: string | null;
}

const BLANK = {
  title: '',
  description: '',
  assignment_mode: 'fixed',
  fixed_assignee_id: '',
  cadence: 'daily',
  due_time: '08:00:00',
  start_date: new Date().toISOString().slice(0, 10),
  proof_type: 'photo',
  photo_count: 1,
  verification_mode: 'manual',
  reward_cents: 100,
  penalty_cents: 0,
  auto_pass_threshold: 0.85,
  auto_fail_threshold: 0.35,
};

export function Chores() {
  const chores = useAdminChores();
  const qc = useQueryClient();
  const [form, setForm] = useState<Record<string, unknown> | null>(null);
  const [preview, setPreview] = useState<PreviewItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (chores.isLoading) return <Spinner />;

  function set(k: string, v: unknown) {
    setForm((f) => ({ ...(f ?? {}), [k]: v }));
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
      await api.post('/chores', form);
      await qc.invalidateQueries({ queryKey: ['chores', 'all'] });
      setForm(null);
      setPreview(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-bold">Chores</h1>
          <Button className="min-h-0 px-3 py-1 text-sm" onClick={() => setForm({ ...BLANK })}>
            New chore
          </Button>
        </div>
        {(chores.data ?? []).map((c) => (
          <Card key={c.id} className={c.id ? '' : ''}>
            <p className="font-semibold">{c.title}</p>
            <p className="text-xs text-slate-400">
              {c.proof_type} · {c.verification_mode} · {money(c.reward_cents)}
              {c.penalty_cents > 0 && ` / -${money(c.penalty_cents)}`}
            </p>
          </Card>
        ))}
      </div>

      {form && (
        <Card className="flex flex-col gap-2">
          <h2 className="font-bold">New chore</h2>
          <Field label="Title">
            <input
              className="inp"
              value={String(form.title)}
              onChange={(e) => set('title', e.target.value)}
            />
          </Field>
          <Field label="Description">
            <input
              className="inp"
              value={String(form.description)}
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
          <Field label="Assignee id (fixed)">
            <input
              className="inp"
              value={String(form.fixed_assignee_id ?? '')}
              onChange={(e) => set('fixed_assignee_id', e.target.value)}
            />
          </Field>
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
          <Field label="Start date">
            <input
              className="inp"
              type="date"
              value={String(form.start_date)}
              onChange={(e) => set('start_date', e.target.value)}
            />
          </Field>
          <Field label="Proof / verification">
            <div className="flex gap-2">
              <select
                className="inp"
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
          <Field label="Reward / penalty ($)">
            <div className="flex gap-2">
              <input
                className="inp"
                type="number"
                value={Number(form.reward_cents) / 100}
                onChange={(e) => set('reward_cents', Math.round(parseFloat(e.target.value) * 100))}
              />
              <input
                className="inp"
                type="number"
                value={Number(form.penalty_cents) / 100}
                onChange={(e) => set('penalty_cents', Math.round(parseFloat(e.target.value) * 100))}
              />
            </div>
          </Field>
          {error && <p className="text-sm text-rose-400">{error}</p>}
          <div className="flex gap-2">
            <Button className="min-h-0 px-3 py-2 text-sm" variant="ghost" onClick={doPreview}>
              Preview
            </Button>
            <Button className="min-h-0 px-3 py-2 text-sm" onClick={save}>
              Save
            </Button>
            <Button
              className="min-h-0 px-3 py-2 text-sm"
              variant="ghost"
              onClick={() => {
                setForm(null);
                setPreview(null);
              }}
            >
              Cancel
            </Button>
          </div>
          {preview && (
            <div className="mt-2 text-xs text-slate-400">
              <p className="font-semibold text-slate-300">Next occurrences</p>
              {preview.map((p) => (
                <p key={p.due_at}>
                  {new Date(p.due_at).toLocaleString()} → {p.assignee_id ?? 'anyone'}
                </p>
              ))}
            </div>
          )}
        </Card>
      )}
    </div>
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
