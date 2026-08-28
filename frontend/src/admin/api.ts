import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { Child, Chore, LedgerEntry, Occurrence } from '../api/types';

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

export type ChoreApply = 'forward' | 'future_generated';

export function useUpdateChore() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      body,
      apply = 'forward',
    }: {
      id: string;
      body: Record<string, unknown>;
      apply?: ChoreApply;
    }) => api.patch<Chore>(`/chores/${id}?apply=${apply}`, body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['chores', 'all'] }),
  });
}

export function useDeactivateChore() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/chores/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['chores', 'all'] }),
  });
}

export const useChildren = () =>
  useQuery({ queryKey: ['children'], queryFn: () => api.get<Child[]>('/children') });

const invalidateChildren = (qc: ReturnType<typeof useQueryClient>) =>
  void qc.invalidateQueries({ queryKey: ['children'] });

export function useCreateChild() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string; display_name: string; password: string }) =>
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
      body: { display_name?: string; is_active?: boolean };
    }) => api.patch<Child>(`/children/${id}`, body),
    onSuccess: () => invalidateChildren(qc),
  });
}

export function useResetChildPassword() {
  return useMutation({
    mutationFn: ({ id, new_password }: { id: string; new_password: string }) =>
      api.post(`/children/${id}/password-reset`, { new_password }),
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

export function useTotpEnroll() {
  return useMutation({
    mutationFn: () => api.post<{ secret: string; provisioning_uri: string }>('/auth/totp/enroll'),
  });
}

export function useTotpConfirm() {
  return useMutation({
    mutationFn: (totp_code: string) => api.post('/auth/totp/confirm', { totp_code }),
  });
}

export function useTotpReset() {
  return useMutation({
    mutationFn: (password: string) => api.post('/auth/totp/reset', { password }),
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
