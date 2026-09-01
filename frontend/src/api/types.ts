export type Role = 'admin' | 'child';

export interface Child {
  id: string;
  username: string;
  display_name: string;
  role: Role;
  is_active: boolean;
  totp_enrolled: boolean;
}

export interface Me {
  id: string;
  username: string;
  display_name: string;
  role: Role;
  csrf_token: string;
  totp_enrolled: boolean;
}

export type OccurrenceStatus =
  | 'pending'
  | 'open'
  | 'submitted'
  | 'verified_pass'
  | 'verified_fail'
  | 'needs_review'
  | 'missed'
  | 'approved'
  | 'rejected'
  | 'excused';

export interface Occurrence {
  id: string;
  chore_id: string;
  assignee_id: string | null;
  window_open_at: string;
  due_at: string;
  status: OccurrenceStatus;
  was_late: boolean;
  settlement_locked_at: string | null;
  reward_cents: number;
  penalty_cents: number;
  outcome_tiers: OutcomeTier[] | null;
  outcome_tier_id: number | null;
  outcome_tier: OutcomeTier | null;
  verification_error: string | null;
}

export type AssignmentMode = 'fixed' | 'rotating' | 'anyone' | 'all';

export interface OutcomeTier {
  id: number;
  condition: string;
  outcome_kind: 'money' | 'text';
  /** Signed: negative is a penalty. The form offers a Reward/Penalty toggle and applies
   *  the sign itself — unlike penalty_cents, which is an unsigned magnitude. */
  amount_cents: number | null;
  text: string | null;
}

export type ChoreKind = 'scheduled' | 'standing';

export interface Chore {
  id: string;
  chore_kind: ChoreKind;
  /** standing chores only — the state a parent flips, and what is in force while on. */
  standing_on: boolean;
  standing_tier_id: number | null;
  standing_since: string | null;
  title: string;
  description: string;
  proof_type: 'photo' | 'location' | 'photo+location' | 'acknowledgement' | 'none';
  photo_count: number;
  photo_prompts: string[];
  allow_gallery_upload: boolean;
  verification_mode: string;
  verification_checklist: { id: number; text: string; required: boolean }[] | null;
  outcome_tiers: OutcomeTier[] | null;
  reward_cents: number;
  penalty_cents: number;
  late_multiplier: number;
  due_time: string;
  cadence: string;
  assignment_mode: AssignmentMode;
  fixed_assignee_id: string | null;
  assignee_ids: string[];
  rotation_period: 'weekly' | 'biweekly' | null;
  rotation_anchor_date: string | null;
  window_open_offset_s: number;
  grace_period_s: number;
  geofence: { lat: number; lon: number; radius_m: number; arrive_before: string | null } | null;
  start_date: string;
  end_date: string | null;
  active: boolean;
  auto_pass_threshold: number;
  auto_fail_threshold: number;
}

export interface SubmissionMedia {
  id: string;
  idx: number;
  prompt_label: string | null;
  url: string | null;
}

export interface Submission {
  id: string;
  occurrence_id: string;
  kind: string;
  source: string;
  note: string | null;
  flags: string[];
  created_at: string;
  media: SubmissionMedia[];
}

export interface Verification {
  id: string;
  verdict: string;
  confidence: number | null;
  reasoning: string | null;
  child_message: string | null;
  checks: { id: number; answer: string; confidence: number; evidence: string }[] | null;
  image_quality_issue: string | null;
  created_by: string;
  created_at: string;
}

export interface Balance {
  child_id: string;
  balance_cents: number;
  currency: string;
}

export interface LedgerEntry {
  id: string;
  kind: string;
  amount_cents: number;
  reason: string;
  created_at: string;
  occurrence_id: string | null;
}

export interface Dispute {
  id: string;
  occurrence_id: string;
  author_user_id: string | null;
  message: string;
  status: 'open' | 'resolved';
  status_at_filing: string | null;
  resolution_note: string | null;
  resolved_at: string | null;
  created_at: string;
}

export interface ChoreStateEvent {
  id: string;
  chore_id: string;
  actor_user_id: string | null;
  state: boolean;
  tier_id: number | null;
  tier: OutcomeTier | null;
  note: string | null;
  created_at: string;
}
