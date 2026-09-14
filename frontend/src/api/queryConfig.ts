import type { QueryClientConfig } from '@tanstack/react-query';

/**
 * Query defaults for the whole app.
 *
 * `refetchOnWindowFocus` is the one that matters here. This is an installed PWA, so
 * reopening it — from the home screen, or by tapping a push — usually resumes the existing
 * document rather than loading a new one. Nothing remounts, so with refetching off the
 * parent was handed whatever had been on screen when they last closed it, and had to
 * pull-to-refresh to see the chore the notification was actually about.
 *
 * `staleTime` keeps that honest rather than chatty: a resume within 15s refetches nothing,
 * so flicking between apps does not restart every query on the screen. React Query v5 drives
 * focus off `visibilitychange`, which is the event a backgrounded PWA actually receives.
 */
export const QUERY_CONFIG: QueryClientConfig = {
  defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: true } },
};
