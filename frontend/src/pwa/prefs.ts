// Which notifications a user wants. Deliberately not in admin/api.ts: kids never load that
// module, and this one card serves both roles from a single self-scoped endpoint.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';

export interface NotificationCategory {
  key: string;
  label: string;
}

export interface PushSettings {
  categories: NotificationCategory[];
  muted: string[];
}

export const usePushSettings = () =>
  useQuery({
    queryKey: ['push-settings'],
    queryFn: () => api.get<PushSettings>('/push/settings'),
  });

export function useSetPushSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (muted: string[]) => api.patch<PushSettings>('/push/settings', { muted }),
    // The server answers with the whole settings object, so seed the cache from the reply
    // rather than refetching a value we were just handed.
    onSuccess: (data) => qc.setQueryData(['push-settings'], data),
  });
}
