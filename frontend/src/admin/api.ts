import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, getPage } from '../api/client';
import type { Child, Chore, ChoreStateEvent, Dispute, LedgerEntry, Occurrence } from '../api/types';

export interface AdminSubmission {
  id: string;
  kind: string;
  source: string;
  note: string | null;
  flags: string[];
  created_at: string;
  geo_distance_m: number | null;
  geo_within: boolean | null;
  media: { id: string; idx: number; prompt_label: string | null; url: string | null }[];
}

export interface AdminVerification {
  id: string;
  kind: string;
  verdict: string;
  confidence: number | null;
  reasoning: string | null;
  child_message: string | null;
  checks: { id: number; answer: string; confidence: number; evidence: string }[] | null;
  image_quality_issue: string | null;
  created_by: string;
  created_at: string;
}

export const useInbox = () =>
  useQuery({
    queryKey: ['inbox'],
    queryFn: () => api.get<Occurrence[]>('/occurrences?inbox=true'),
  });

/** Misses a parent has not settled yet. A miss sits at `missed` until it is excused or
 *  decided, so the list needs no date window — deciding one drops it out. Newest first,
 *  so an old backlog sinks rather than burying today's. */
export const useMissed = () =>
  useQuery({
    queryKey: ['inbox', 'missed'],
    queryFn: () => api.get<Occurrence[]>('/occurrences?status=missed&order=desc&limit=200'),
  });

/** Everything still scheduled, soonest first; the view keeps the next one per chore and kid. */
export const useUpcoming = () =>
  useQuery({
    queryKey: ['inbox', 'upcoming'],
    queryFn: () => api.get<Occurrence[]>('/occurrences?status=pending&order=asc&limit=500'),
  });

export const useAdminOccurrence = (id: string) =>
  useQuery({
    queryKey: ['occurrence', id],
    queryFn: () => api.get<Occurrence>(`/occurrences/${id}`),
  });

export const useAdminSubmissions = (id: string) =>
  useQuery({
    queryKey: ['submissions', id],
    queryFn: () => api.get<AdminSubmission[]>(`/occurrences/${id}/submissions`),
  });

export const useAdminVerifications = (id: string) =>
  useQuery({
    queryKey: ['verifications', id],
    queryFn: () => api.get<AdminVerification[]>(`/occurrences/${id}/verifications`),
  });

export interface Decision {
  action: 'approve' | 'reject' | 'excuse' | 'redo' | 'tier';
  reason: string;
  amount_override_cents?: number | null;
  /** action: 'tier' only — the tier takes its amount from the chore, so no override. */
  tier_id?: number;
}

export function useDecision() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Decision }) =>
      api.post(`/occurrences/${id}/decision`, body),
    onSuccess: (_d, { id }) => {
      void qc.invalidateQueries({ queryKey: ['inbox'] });
      void qc.invalidateQueries({ queryKey: ['history'] });
      void qc.invalidateQueries({ queryKey: ['occurrence', id] });
      void qc.invalidateQueries({ queryKey: ['verifications', id] });
      // Re-deciding writes reversing ledger entries, so money moves too (spec §9).
      void qc.invalidateQueries({ queryKey: ['ledger'] });
      void qc.invalidateQueries({ queryKey: ['balance'] });
    },
  });
}

export interface HistoryQuery {
  child?: string;
  chore?: string;
  statuses: string[];
  from?: string;
  to?: string;
  limit: number;
  offset: number;
}

export function historyQs(q: HistoryQuery): string {
  const qs = new URLSearchParams({
    order: 'desc',
    limit: String(q.limit),
    offset: String(q.offset),
  });
  if (q.child) qs.set('child', q.child);
  if (q.chore) qs.set('chore', q.chore);
  if (q.from) qs.set('from', q.from);
  if (q.to) qs.set('to', q.to);
  q.statuses.forEach((s) => qs.append('status', s));
  return qs.toString();
}

export const useHistory = (q: HistoryQuery) =>
  useQuery({
    queryKey: ['history', q],
    queryFn: () => getPage<Occurrence[]>(`/occurrences?${historyQs(q)}`),
    placeholderData: (prev) => prev,
  });

export interface DisputeWithContext extends Dispute {
  chore_title: string | null;
  author_name: string | null;
  occurrence_status: string | null;
  occurrence_due_at: string | null;
}

export const useOpenDisputes = () =>
  useQuery({
    queryKey: ['disputes', 'open'],
    queryFn: () => api.get<DisputeWithContext[]>('/disputes?status=open'),
  });

export const useOccurrenceDisputes = (id: string) =>
  useQuery({
    enabled: !!id,
    queryKey: ['disputes', id],
    queryFn: () => api.get<Dispute[]>(`/occurrences/${id}/disputes`),
  });

export function useResolveDispute() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) =>
      api.post(`/disputes/${id}/resolve`, { note }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['disputes'] }),
  });
}

export const useAdminChores = () =>
  useQuery({
    queryKey: ['chores', 'all'],
    queryFn: () => api.get<Chore[]>('/chores?include_inactive=true'),
  });

export function useUpdateChore() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api.patch<Chore>(`/chores/${id}`, body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['chores', 'all'] }),
  });
}

export function useDuplicateChore() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<Chore>(`/chores/${id}/duplicate`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['chores', 'all'] }),
  });
}

export function useSetChoreState() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: string;
      body: { on: boolean; tier_id?: number | null; note?: string | null };
    }) => api.post<Chore>(`/chores/${id}/state`, body),
    onSuccess: (_d, { id }) => {
      void qc.invalidateQueries({ queryKey: ['chores', 'all'] });
      void qc.invalidateQueries({ queryKey: ['chores'] });
      void qc.invalidateQueries({ queryKey: ['chore-state', id] });
    },
  });
}

export const useChoreStateHistory = (id: string | null) =>
  useQuery({
    queryKey: ['chore-state', id],
    enabled: id != null,
    queryFn: () => api.get<ChoreStateEvent[]>(`/chores/${id}/state/history`),
  });

export function useDeactivateChore() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/chores/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['chores', 'all'] }),
  });
}

export interface PenaltyApply {
  chore_id: string;
  child_id: string;
  tier_id: number;
  /** Positive magnitude; the backend applies the sign, like a payout. */
  amount_override_cents?: number;
  note?: string;
}

/** Charge a kid against a penalty rule (spec §4.8). Invalidated wide: the statement and the
 *  balance both move, and MeShell reads the balance in its header. */
export function useApplyPenalty() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PenaltyApply) => api.post<LedgerEntry>('/penalties', body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['ledger'] });
      void qc.invalidateQueries({ queryKey: ['balance'] });
    },
  });
}

/** Undo an applied penalty with a compensating entry — the charge stays on the statement
 *  with its undo beside it (spec §9, append-only). */
export function useReversePenalty() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      api.post<LedgerEntry>(`/penalties/${id}/reverse`, { reason }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['ledger'] });
      void qc.invalidateQueries({ queryKey: ['balance'] });
    },
  });
}

export const useChildren = () =>
  useQuery({ queryKey: ['children'], queryFn: () => api.get<Child[]>('/children') });

const invalidateChildren = (qc: ReturnType<typeof useQueryClient>) =>
  void qc.invalidateQueries({ queryKey: ['children'] });

export function useCreateChild() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string; display_name: string; email: string }) =>
      api.post<Child>('/children', body),
    onSuccess: () => invalidateChildren(qc),
  });
}

export function useUpdateChild() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: string;
      body: { display_name?: string; email?: string; is_active?: boolean };
    }) => api.patch<Child>(`/children/${id}`, body),
    onSuccess: () => invalidateChildren(qc),
  });
}

export function useDeactivateChild() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/children/${id}`),
    onSuccess: () => invalidateChildren(qc),
  });
}

export function useRotateCheckinToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post(`/children/${id}/checkin-token/rotate`),
    onSuccess: (_d, id) => void qc.invalidateQueries({ queryKey: ['checkin-token', id] }),
  });
}

export const useChildBalance = (childId: string) =>
  useQuery({
    enabled: !!childId,
    queryKey: ['balance', childId],
    queryFn: () => api.get<{ balance_cents: number }>(`/children/${childId}/balance`),
  });

export const useChildLedger = (childId: string) =>
  useQuery({
    enabled: !!childId,
    queryKey: ['ledger', childId],
    queryFn: () => api.get<LedgerEntry[]>(`/children/${childId}/ledger`),
  });

export function usePayout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      child_id: string;
      amount_cents: number;
      method: string;
      note: string;
      covers_through?: string;
    }) => api.post('/payouts', body),
    onSuccess: (_d, body) => {
      void qc.invalidateQueries({ queryKey: ['balance', body.child_id] });
      void qc.invalidateQueries({ queryKey: ['ledger', body.child_id] });
    },
  });
}

export interface JobsDashboard {
  queue: Record<string, number>;
  stuck_jobs: number;
  scheduler: { last_tick_at: string | null; stale: boolean };
  recent_failures: { id: string; occurrence_id: string; error: string | null }[];
  checkins: { child: string; last_seen: string | null; stale: boolean }[];
}

export const useJobsDashboard = () =>
  useQuery({ queryKey: ['admin-jobs'], queryFn: () => api.get<JobsDashboard>('/admin/jobs') });

export interface AdminSettings {
  llm: {
    base_url: string;
    model: string;
    api_key_set: boolean;
    timeout_s: number;
    max_retries: number;
  };
  verification: { auto_pass_threshold: number; auto_fail_threshold: number };
  source: Record<string, 'db' | 'env'>;
}

export type SettingsPatch = Partial<{
  llm_base_url: string | null;
  llm_model: string | null;
  llm_api_key: string | null;
  llm_timeout_s: number | null;
  llm_max_retries: number | null;
  auto_pass_threshold: number | null;
  auto_fail_threshold: number | null;
}>;

export const useSettings = () =>
  useQuery({ queryKey: ['settings'], queryFn: () => api.get<AdminSettings>('/admin/settings') });

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SettingsPatch) => api.patch<AdminSettings>('/admin/settings', body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['settings'] }),
  });
}

export interface LlmModels {
  reachable: boolean;
  models: string[];
  error?: string;
  status_code?: number;
}

export function useLlmModels(baseUrl: string, apiKey: string) {
  return useQuery({
    enabled: false, // probe on demand via refetch()
    queryKey: ['llm-models', baseUrl],
    queryFn: () => {
      const qs = new URLSearchParams({ base_url: baseUrl });
      if (apiKey) qs.set('api_key', apiKey);
      return api.get<LlmModels>(`/admin/llm/models?${qs.toString()}`);
    },
  });
}

/** The local admin password — the way back in when Cloudflare or Google is unavailable. */
export function useSetBreakGlassPassword() {
  return useMutation({
    mutationFn: (new_password: string) => api.post('/admin/break-glass-password', { new_password }),
  });
}

/** A parent's own sign-in details. Changing the address signs you out — the session was
 *  minted for the old identity and Access decides who is at the keyboard. */
export function useUpdateProfile() {
  return useMutation({
    mutationFn: (body: { display_name?: string; email?: string }) =>
      api.patch<{ email: string | null; signed_out: boolean }>('/admin/profile', body),
  });
}

export const useCheckinToken = (childId: string) =>
  useQuery({
    enabled: !!childId,
    queryKey: ['checkin-token', childId],
    queryFn: () =>
      api.get<{ token: string; webhook_url: string; last_used_at: string | null; stale: boolean }>(
        `/children/${childId}/checkin-token`,
      ),
  });

// --- household backup ------------------------------------------------------

export interface ImportResult {
  counts: Record<string, number>;
  warnings: string[];
  dry_run: boolean;
  csrf_token: string | null;
}

/** Restore a backup bundle. `dry_run` reports what would happen and changes nothing. */
export function useImportBundle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { bundle: unknown; dry_run?: boolean }) =>
      api.post<ImportResult>('/admin/import', body),
    onSuccess: (result) => {
      // A real restore replaced every row; nothing already cached is still true.
      if (!result.dry_run) qc.clear();
    },
  });
}
