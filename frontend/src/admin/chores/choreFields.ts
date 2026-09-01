// Constants and pure helpers for the chore form. Split out of Chores.tsx so the sections,
// the state hook and the list can share them without importing each other.

export interface PreviewItem {
  due_at: string;
  window_open_at: string;
  assignee_id: string | null;
}

export const BLANK: Record<string, unknown> = {
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
  geofence: null,
  verification_mode: 'manual',
  verification_rule: '',
  reward_cents: 100,
  penalty_cents: 0,
  auto_pass_threshold: 0.85,
  auto_fail_threshold: 0.35,
};

// Fields the backend PATCH accepts (spec §4.1 ChoreUpdate) — proof_type / start_date excluded.
export const EDITABLE = [
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
  'verification_mode',
  'verification_rule',
  'verification_checklist',
  'reward_cents',
  'penalty_cents',
  'auto_pass_threshold',
  'auto_fail_threshold',
] as const;

// Proof types where the kid sends photos (spec §4.1).
export const PHOTO_PROOFS = new Set(['photo', 'photo+location']);

// Proof types that check where the kid is, and so need a fence (spec §6.2).
export const FENCED = new Set(['location', 'photo+location']);

// Modes that send the photo to the vision model. The backend rejects them for a proof_type
// with no image (app/schemas/chore.py), and only these modes ever read the rule, the
// checklist or the thresholds (app/worker/verify.py) — so all four are photo-only fields.
export const LLM_MODES = new Set(['llm_assist', 'llm_auto']);

// Accepted by backend cadence parser (app/services/cadence.py).
export const CADENCE_EXAMPLES = [
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
export const HOURS_BEFORE = (secs: number) => Math.round((-secs / 3600) * 100) / 100;

/** What the offset means on the clock, which is what a parent actually pictures. */
export function opensAt(dueTime: string, offsetSecs: number): string {
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

// A one-off carries its date inside the cadence: once(YYYY-MM-DD). Keeping the date in the
// token (rather than reusing start_date) means the scheduler's window clamping can't turn it
// into a daily chore, and it stays reschedulable — cadence is in EDITABLE, start_date is not.
const ONCE_RE = /^once\((\d{4}-\d{2}-\d{2})\)$/i;

/** The YYYY-MM-DD of a one-off cadence, or null if this cadence is a recurring one. */
export function onceDate(cadence: string): string | null {
  return ONCE_RE.exec(cadence.trim())?.[1] ?? null;
}

export const ONCE_TODAY = () => `once(${new Date().toISOString().slice(0, 10)})`;
