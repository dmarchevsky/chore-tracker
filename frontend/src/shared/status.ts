// One vocabulary for occurrence status and anti-cheat flags, so the parent and kid views
// can't drift and neither one ever shows a raw enum value.

import type { OccurrenceStatus } from '../api/types';

export type Tone = 'go' | 'wait' | 'good' | 'bad' | 'idle';

export const TONE_CLASS: Record<Tone, string> = {
  go: 'text-sky-400',
  wait: 'text-amber-400',
  good: 'text-emerald-400',
  bad: 'text-rose-400',
  idle: 'text-slate-400',
};

export interface Label {
  label: string;
  tone: Tone;
}

/** What a parent needs to know: whose move is it, and did anyone decide yet. */
export const ADMIN_STATUS: Record<OccurrenceStatus, Label> = {
  pending: { label: 'Scheduled', tone: 'idle' },
  open: { label: 'Waiting on kid', tone: 'go' },
  submitted: { label: 'Checking…', tone: 'wait' },
  needs_review: { label: 'Needs your review', tone: 'wait' },
  verified_pass: { label: 'AI passed', tone: 'good' },
  verified_fail: { label: 'AI failed', tone: 'bad' },
  missed: { label: 'Missed', tone: 'bad' },
  approved: { label: 'Approved', tone: 'good' },
  rejected: { label: 'Rejected', tone: 'bad' },
  excused: { label: 'Excused', tone: 'idle' },
};

/** What a kid needs to know: is there something to do, and did it count. */
export const KID_STATUS: Record<OccurrenceStatus, Label> = {
  pending: { label: 'Later', tone: 'idle' },
  open: { label: 'Do it', tone: 'go' },
  submitted: { label: 'Waiting', tone: 'wait' },
  needs_review: { label: 'Waiting', tone: 'wait' },
  verified_pass: { label: 'Done ✅', tone: 'good' },
  verified_fail: { label: 'Do it', tone: 'go' },
  missed: { label: 'Missed', tone: 'bad' },
  approved: { label: 'Done ✅', tone: 'good' },
  rejected: { label: 'Missed', tone: 'bad' },
  excused: { label: 'Excused', tone: 'idle' },
};

export function statusEntry(status: string, role: 'admin' | 'kid' = 'admin'): Label {
  const map = role === 'kid' ? KID_STATUS : ADMIN_STATUS;
  return map[status as OccurrenceStatus] ?? { label: status, tone: 'idle' };
}

export const statusLabel = (status: string, role: 'admin' | 'kid' = 'admin'): string =>
  statusEntry(status, role).label;

// Anti-cheat / quality flags, in the words a parent would use (spec §6.1). Flags are an
// input to routing and are never an auto-fail, so the wording stays descriptive.
const FLAG_LABEL: Record<string, string> = {
  GALLERY_UPLOAD: 'picked from the gallery, not taken in the app',
  DUPLICATE_SUSPECTED: 'looks like a photo sent before',
  STALE_CAPTURE: 'taken well before it was sent',
  NO_EXIF: 'no camera metadata',
  SCREENSHOT_SUSPECTED: 'could be a screenshot',
  LOW_ACCURACY: 'weak GPS fix',
  OUTSIDE_GEOFENCE: 'checked in outside the area',
};

export const flagLabel = (flag: string): string => FLAG_LABEL[flag] ?? flag;

// Verification verdicts (`Verdict` on the verification row) are a different axis from
// occurrence status: what the model or the parent said, not where the chore stands.
const VERDICT_LABEL: Record<string, string> = {
  pass: 'Pass',
  fail: 'Fail',
  needs_review: 'Not sure',
  error: 'Error',
};

export const verdictLabel = (verdict: string): string => VERDICT_LABEL[verdict] ?? verdict;
