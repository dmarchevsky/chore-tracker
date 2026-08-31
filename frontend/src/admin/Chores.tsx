import { useState } from 'react';
import { useAdminChores, useChildren, useDeactivateChore, useUpdateChore } from './api';
import { api } from '../api/client';
import { useQueryClient } from '@tanstack/react-query';
import type { Chore } from '../api/types';
import { Button, Card, Spinner } from '../shared/ui';
import { ChecklistField, type ChecklistItem } from './ChecklistField';
import { GeofenceField } from './GeofenceField';
import { DEFAULT_FENCE, type Geofence } from '../shared/coords';
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
  window_open_offset_s: -12 * 3600,
  start_date: new Date().toISOString().slice(0, 10),
  proof_type: 'photo',
  photo_count: 1,
  photo_prompts: [],
  allow_gallery_upload: false,
  prompt_token_enabled: false,
  geofence: null,
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
  'window_open_offset_s',
  'geofence',
  'photo_count',
  'photo_prompts',
  'allow_gallery_upload',
  'prompt_token_enabled',
  'verification_mode',
  'verification_rule',
  'verification_checklist',
  'reward_cents',
  'penalty_cents',
  'auto_pass_threshold',
  'auto_fail_threshold',
] as const;

// Proof types where the kid sends photos (spec §4.1).
const PHOTO_PROOFS = new Set(['photo', 'photo+location']);

// Proof types that check where the kid is, and so need a fence (spec §6.2).
const FENCED = new Set(['location', 'photo+location']);

// Accepted by backend cadence parser (app/services/cadence.py).
const CADENCE_EXAMPLES = [
  'daily',
  'weekdays',
  'weekends',
  'weekly(on=[SAT])',
  'weekly(on=[MON,WED,FRI])',
  'monthly(day=15)',
];

// window_open_offset_s is a negative offset from the due time (backend bounds: 0 to
// -14 days). The form takes hours, but keeps the raw seconds so an offset that isn't a
// whole number of hours round-trips untouched when nobody edits the field.
const HOURS_BEFORE = (secs: number) => Math.round((-secs / 3600) * 100) / 100;

/** What the offset means on the clock, which is what a parent actually pictures. */
function opensAt(dueTime: string, offsetSecs: number): string {
  const [h, m] = dueTime.split(':').map(Number);
  const due = new Date(2000, 0, 3, h || 0, m || 0); // an arbitrary date; only the clock matters
  const open = new Date(due.getTime() + offsetSecs * 1000);
  const clock = open.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const midnight = (d: Date) => new Date(d).setHours(0, 0, 0, 0);
  const days = Math.round((midnight(due) - midnight(open)) / 86_400_000);
  if (days === 0) return `opens ${clock}, the same day`;
  if (days === 1) return `opens ${clock} the day before`;
  return `opens ${clock}, ${days} days before`;
}

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
  const [preview, setPreview] = useState<PreviewItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  function set(k: string, v: unknown) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  /** photo_prompts is either empty or exactly photo_count long — the backend rejects
   *  anything else, and the kid's capture screen builds its slots from the labels. */
  function setPhotoCount(n: number) {
    const count = Math.min(Math.max(n || 1, 1), 6);
    setForm((f) => {
      const labels = (f.photo_prompts as string[]) ?? [];
      const next = labels.length
        ? Array.from({ length: count }, (_, i) => labels[i] ?? '')
        : labels;
      return { ...f, photo_count: count, photo_prompts: next };
    });
  }

  function setLabel(idx: number, text: string) {
    setForm((f) => {
      const count = Number(f.photo_count) || 1;
      const labels = Array.from(
        { length: count },
        (_, i) => ((f.photo_prompts as string[]) ?? [])[i] ?? '',
      );
      labels[idx] = text;
      // All blank means "no labels" — send [] rather than a row of empty strings.
      return { ...f, photo_prompts: labels.some((x) => x.trim()) ? labels : [] };
    });
  }

  function setAssignmentMode(mode: string) {
    setForm((f) => {
      const next: Record<string, unknown> = { ...f, assignment_mode: mode };
      if (mode === 'rotating') {
        if (!next.rotation_period) next.rotation_period = 'weekly';
        if (!next.rotation_anchor_date)
          next.rotation_anchor_date = new Date().toISOString().slice(0, 10);
      }
      return next;
    });
  }

  async function doPreview() {
    setError(null);
    try {
      setPreview(await api.post<PreviewItem[]>('/chores/preview?count=8', form));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  // Only send the assignee fields that matter for the chosen mode.
  function assignmentBody(src: Record<string, unknown>): Record<string, unknown> {
    const mode = src.assignment_mode;
    const out = { ...src };
    out.fixed_assignee_id = mode === 'fixed' ? src.fixed_assignee_id || null : null;
    if (mode !== 'rotating' && mode !== 'all') out.assignee_ids = [];
    if (mode !== 'rotating') {
      out.rotation_period = null;
      out.rotation_anchor_date = null;
    }
    return out;
  }

  /** proof_type is immutable, so it is not in the PATCH allowlist — take it from the
   *  form. A chore that doesn't check location must not carry a stale fence. */
  function body(src: Record<string, unknown>): Record<string, unknown> {
    const out = assignmentBody(src);
    if (!FENCED.has(String(form.proof_type))) out.geofence = null;
    if (!PHOTO_PROOFS.has(String(form.proof_type))) {
      out.photo_prompts = [];
      out.allow_gallery_upload = false;
      out.prompt_token_enabled = false;
    }
    return out;
  }

  async function save() {
    setError(null);
    try {
      if (editing) {
        const patch: Record<string, unknown> = {};
        for (const k of EDITABLE) patch[k] = form[k];
        await update.mutateAsync({ id: chore!.id, body: body(patch) });
      } else {
        await api.post('/chores', body(form));
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
          onChange={(e) => setAssignmentMode(e.target.value)}
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

      {(form.assignment_mode === 'rotating' || form.assignment_mode === 'all') && (
        <Field label={form.assignment_mode === 'all' ? 'Everyone' : 'Rotation between'}>
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
      )}

      {form.assignment_mode === 'rotating' && (
        <Field label="Rotation period / anchor">
          <div className="flex gap-2">
            <select
              className="inp"
              value={String(form.rotation_period ?? '')}
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
      )}

      <Field label="Cadence">
        <input
          className="inp"
          list="cadence-options"
          placeholder="daily"
          value={String(form.cadence)}
          onChange={(e) => set('cadence', e.target.value)}
        />
        <datalist id="cadence-options">
          {CADENCE_EXAMPLES.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
        <div className="mt-1 flex flex-wrap gap-1">
          {CADENCE_EXAMPLES.map((c) => (
            <button
              key={c}
              type="button"
              className={`rounded border px-2 py-0.5 text-xs ${
                form.cadence === c
                  ? 'border-sky-500 text-sky-300'
                  : 'border-slate-700 text-slate-400'
              }`}
              onClick={() => set('cadence', c)}
            >
              {c}
            </button>
          ))}
        </div>
        <p className="mt-1 text-xs text-slate-500">
          <code>daily</code>, <code>weekdays</code> (Mon–Fri), <code>weekends</code> (Sat–Sun),{' '}
          <code>weekly(on=[SAT])</code> or <code>weekly(on=[MON,WED,FRI])</code>, or{' '}
          <code>monthly(day=15)</code> (clamped to the last day of shorter months). The time of day
          comes from the “Due time” field below.
        </p>
      </Field>
      <Field label="Due time">
        <input
          className="inp"
          type="time"
          value={String(form.due_time).slice(0, 5)}
          onChange={(e) => set('due_time', `${e.target.value}:00`)}
        />
      </Field>
      <Field label="Opens (hours before it’s due)">
        <input
          className="inp"
          type="number"
          step="0.25"
          min="0"
          max="336"
          value={HOURS_BEFORE(Number(form.window_open_offset_s))}
          onChange={(e) =>
            set('window_open_offset_s', -Math.round(parseFloat(e.target.value || '0') * 3600))
          }
        />
        <p className="mt-1 text-xs text-slate-500">
          {opensAt(String(form.due_time), Number(form.window_open_offset_s))} — a kid can’t submit
          before that.
        </p>
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
      {PHOTO_PROOFS.has(String(form.proof_type)) && (
        <div className="flex flex-col gap-2 rounded-xl border border-slate-800 p-3">
          <span className="text-sm font-semibold text-slate-300">What the kid sends</span>

          <Field label="How many photos">
            <input
              className="inp"
              type="number"
              min="1"
              max="6"
              value={Number(form.photo_count) || 1}
              onChange={(e) => setPhotoCount(Number(e.target.value))}
            />
          </Field>

          {Array.from({ length: Number(form.photo_count) || 1 }, (_, i) => (
            <Field key={i} label={`Photo ${i + 1} — what should it show?`}>
              <input
                className="inp"
                placeholder={i === 0 ? 'sink close-up' : 'wide kitchen'}
                value={((form.photo_prompts as string[]) ?? [])[i] ?? ''}
                onChange={(e) => setLabel(i, e.target.value)}
              />
            </Field>
          ))}
          <p className="text-xs text-slate-500">
            Labels name each shot for the kid and travel with the photo to the AI and the review
            pane. Two angles — a close-up and a wide shot — make staging a photo much harder. Leave
            them blank for unlabelled photos.
          </p>

          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={Boolean(form.allow_gallery_upload)}
              onChange={(e) => set('allow_gallery_upload', e.target.checked)}
            />
            Allow picking an existing photo
          </label>
          <p className="text-xs text-slate-500">
            Off means the in-app camera only. Anything picked from the gallery is flagged and always
            comes to you for review.
          </p>

          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={Boolean(form.prompt_token_enabled)}
              onChange={(e) => set('prompt_token_enabled', e.target.checked)}
            />
            Show a random number to hold in the photo
          </label>
          <p className="text-xs text-slate-500">
            A new 2-digit number each time, shown on the kid’s camera screen and added as a required
            AI check. It’s the only thing here that defeats a screenshot or a friend’s photo — worth
            it for the chores that matter, overkill for the rest.
          </p>
        </div>
      )}

      {FENCED.has(String(form.proof_type)) && (
        <GeofenceField
          value={(form.geofence as Geofence | null) ?? DEFAULT_FENCE}
          onChange={(g) => set('geofence', g)}
        />
      )}

      <Field label="Verification rule (natural language)">
        <input
          className="inp"
          value={String(form.verification_rule ?? '')}
          onChange={(e) => set('verification_rule', e.target.value)}
        />
      </Field>

      <ChecklistField
        value={(form.verification_checklist as ChecklistItem[] | null) ?? null}
        onChange={(items) => set('verification_checklist', items)}
      />

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
        <p className="text-xs text-slate-500">
          Saving regenerates upcoming occurrences; completed ones are left alone.
        </p>
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
                .mutateAsync({ id: chore!.id, body: { active: true } })
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

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-slate-400">{label}</span>
      {children}
    </label>
  );
}
