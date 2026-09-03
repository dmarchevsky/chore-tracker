// Constants and pure helpers for the chore form. Split out of Chores.tsx so the sections,
// the state hook and the list can share them without importing each other.
import type { OutcomeTier } from '../../api/types';

export interface PreviewItem {
  due_at: string;
  window_open_at: string;
  assignee_id: string | null;
}

export const BLANK: Record<string, unknown> = {
  chore_kind: 'scheduled',
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
  grace_period_s: 15 * 60,
  end_date: null,
  start_date: new Date().toISOString().slice(0, 10),
  proof_type: 'photo',
  photo_count: 1,
  photo_prompts: [],
  allow_gallery_upload: false,
  geofence: null,
  verification_mode: 'manual',
  outcome_tiers: null,
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
  'grace_period_s',
  'end_date',
  'geofence',
  'photo_count',
  'photo_prompts',
  'allow_gallery_upload',
  'verification_mode',
  'verification_checklist',
  'outcome_tiers',
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

// The cadence/window humanisers moved to shared/schedule.ts once the kid's rules screen
// needed them too; re-exported here so the form sections keep one import.
export { opensAt, onceDate } from '../../shared/schedule';

export const ONCE_TODAY = () => `once(${new Date().toISOString().slice(0, 10)})`;

/** A tiered chore's money comes from its tiers, so the flat reward/penalty pair is hidden
 *  and the backend pins both to 0 (app/schemas/chore.py). */
export const isTiered = (form: Record<string, unknown>): boolean =>
  Boolean((form.outcome_tiers as unknown[] | null)?.length);

/** A standing chore has no schedule, no proof and no money — it is a state a parent flips. */
export const isStanding = (form: Record<string, unknown>): boolean =>
  form.chore_kind === 'standing';

/** A penalty rule has no schedule and no proof either — it is a published price list a
 *  parent charges against, and its tiers are the conditions and what each one costs. */
export const isPenalty = (form: Record<string, unknown>): boolean => form.chore_kind === 'penalty';

/** Neither kind is materialised into occurrences, so both hide the whole schedule/proof
 *  half of the form and are limited to the assignment modes that name a kid. */
export const isUnscheduled = (form: Record<string, unknown>): boolean =>
  isStanding(form) || isPenalty(form);

/** 1-based ids of outcome rows the backend will reject.
 *
 * "Add an outcome" seeds a blank row, and the backend rejects a blank condition with a field
 * error the parent has no way to act on — so catch it here, where we can point at the row.
 */
export function incompleteTiers(tiers: OutcomeTier[] | null | undefined): number[] {
  return (tiers ?? [])
    .filter(
      (t) => !t.condition.trim() || (t.outcome_kind === 'text' ? !t.text?.trim() : !t.amount_cents),
    )
    .map((t) => t.id);
}

/** 1-based ids of penalty-rule outcomes the backend will reject on top of the above: a
 *  penalty rule only takes money away, so every tier must be money and negative. */
export function nonPenaltyTiers(tiers: OutcomeTier[] | null | undefined): number[] {
  return (tiers ?? [])
    .filter((t) => t.outcome_kind !== 'money' || (t.amount_cents ?? 0) >= 0)
    .map((t) => t.id);
}
