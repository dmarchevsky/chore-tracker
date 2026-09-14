import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { QUERY_CONFIG } from './queryConfig';

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', { value: state, configurable: true });
  // React Query v5 listens on `window`, and a real visibilitychange reaches it by bubbling
  // up from document — so a synthetic one has to bubble too or nothing hears it.
  document.dispatchEvent(new Event('visibilitychange', { bubbles: true }));
}

afterEach(() => {
  setVisibility('visible');
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function mount(fetches: { n: number }) {
  const qc = new QueryClient(QUERY_CONFIG);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return renderHook(
    () =>
      useQuery({
        queryKey: ['thing'],
        queryFn: () => {
          fetches.n += 1;
          return Promise.resolve('ok');
        },
      }),
    { wrapper },
  );
}

describe('query defaults', () => {
  it('refetches when the app comes back to the foreground', async () => {
    // The reported bug: open the app from a push and you are looking at yesterday's screen
    // until you pull to refresh. An installed PWA resumes its document instead of
    // remounting, so a focus refetch is the only thing that brings the data forward.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetches = { n: 0 };
    const { result } = mount(fetches);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(fetches.n).toBe(1);

    // Backgrounded, time passes, reopened.
    setVisibility('hidden');
    await vi.advanceTimersByTimeAsync(20_000);
    setVisibility('visible');

    await waitFor(() => expect(fetches.n).toBe(2));
  });

  it('does not refetch on a quick flick away and back', async () => {
    // staleTime is what keeps the above from restarting every query on screen every time
    // the parent glances at another app.
    const fetches = { n: 0 };
    const { result } = mount(fetches);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    setVisibility('hidden');
    setVisibility('visible');

    await new Promise((r) => setTimeout(r, 50));
    expect(fetches.n).toBe(1);
  });
});
