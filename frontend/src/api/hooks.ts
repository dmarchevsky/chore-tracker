import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';
import type { Balance, Chore, LedgerEntry, Occurrence } from './types';

export interface OccurrenceQuery {
  inbox?: boolean;
  status?: string;
  from?: string;
  to?: string;
  order?: 'asc' | 'desc';
  limit?: number;
}

export function useOccurrences(params?: OccurrenceQuery) {
  const qs = new URLSearchParams();
  if (params?.inbox) qs.set('inbox', 'true');
  if (params?.status) qs.set('status', params.status);
  if (params?.from) qs.set('from', params.from);
  if (params?.to) qs.set('to', params.to);
  if (params?.order) qs.set('order', params.order);
  if (params?.limit) qs.set('limit', String(params.limit));
  return useQuery({
    queryKey: ['occurrences', params],
    queryFn: () => api.get<Occurrence[]>(`/occurrences?${qs}`),
  });
}

export function useOccurrence(id: string) {
  return useQuery({
    queryKey: ['occurrence', id],
    queryFn: () => api.get<Occurrence>(`/occurrences/${id}`),
  });
}

export function useChore(id: string | undefined) {
  return useQuery({
    enabled: !!id,
    queryKey: ['chore', id],
    queryFn: () => api.get<Chore>(`/chores/${id}`),
  });
}

export function useChores() {
  return useQuery({ queryKey: ['chores'], queryFn: () => api.get<Chore[]>('/chores') });
}

export function useBalance(childId: string) {
  return useQuery({
    enabled: !!childId,
    queryKey: ['balance', childId],
    queryFn: () => api.get<Balance>(`/children/${childId}/balance`),
  });
}

export function useLedger(childId: string) {
  return useQuery({
    enabled: !!childId,
    queryKey: ['ledger', childId],
    queryFn: () => api.get<LedgerEntry[]>(`/children/${childId}/ledger`),
  });
}

export function useDispute(occId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (message: string) => api.post(`/occurrences/${occId}/dispute`, { message }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['occurrence', occId] }),
  });
}
