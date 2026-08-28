import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { Chore, LedgerEntry, Occurrence } from '../api/types';

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
  action: 'approve' | 'reject' | 'excuse' | 'redo';
  reason: string;
  amount_override_cents?: number | null;
}

export function useDecision() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Decision }) =>
      api.post(`/occurrences/${id}/decision`, body),
    onSuccess: (_d, { id }) => {
      void qc.invalidateQueries({ queryKey: ['inbox'] });
      void qc.invalidateQueries({ queryKey: ['occurrence', id] });
    },
  });
}

export const useAdminChores = () =>
  useQuery({
    queryKey: ['chores', 'all'],
    queryFn: () => api.get<Chore[]>('/chores?include_inactive=true'),
  });

export const useChildren = () =>
  useQuery({
    queryKey: ['children'],
    queryFn: () => api.get<{ id: string; display_name: string; is_active: boolean }[]>('/children'),
  });

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
  recent_failures: { id: string; occurrence_id: string; error: string | null }[];
  checkins: { child: string; last_seen: string | null; stale: boolean }[];
}

export const useJobsDashboard = () =>
  useQuery({ queryKey: ['admin-jobs'], queryFn: () => api.get<JobsDashboard>('/admin/jobs') });

export const useCheckinToken = (childId: string) =>
  useQuery({
    enabled: !!childId,
    queryKey: ['checkin-token', childId],
    queryFn: () =>
      api.get<{ token: string; webhook_url: string; last_used_at: string | null; stale: boolean }>(
        `/children/${childId}/checkin-token`,
      ),
  });
