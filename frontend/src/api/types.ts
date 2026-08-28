export type Role = 'admin' | 'child';

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
  prompt_token: string | null;
  verification_error: string | null;
}

export interface Chore {
  id: string;
  title: string;
  description: string;
  proof_type: 'photo' | 'location' | 'photo+location' | 'acknowledgement' | 'none';
  photo_count: number;
  photo_prompts: string[];
  allow_gallery_upload: boolean;
  prompt_token_enabled: boolean;
  verification_mode: string;
  reward_cents: number;
  penalty_cents: number;
  due_time: string;
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
