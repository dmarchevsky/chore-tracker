import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useDecision, useOpenDisputes } from './api';

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

afterEach(() => vi.restoreAllMocks());

describe('useDecision', () => {
  it('refetches the open appeals, so a reviewed chore leaves the inbox', async () => {
    // Deciding a disputed chore closes its appeal server-side. Without the matching
    // invalidation the parent still sees it under "Kids say something is wrong" until they
    // reload — which is exactly what a fixed backend would look like from the sofa.
    const urls: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input);
      if ((init?.method ?? 'GET') === 'GET') urls.push(url);
      return Promise.resolve(json([]));
    });

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => ({ disputes: useOpenDisputes(), decide: useDecision() }), {
      wrapper,
    });

    await waitFor(() => expect(result.current.disputes.isSuccess).toBe(true));
    const before = urls.filter((u) => u.includes('/disputes')).length;
    expect(before).toBe(1);

    result.current.decide.mutate({ id: 'o1', body: { action: 'approve', reason: 'ok' } });

    await waitFor(() =>
      expect(urls.filter((u) => u.includes('/disputes')).length).toBeGreaterThan(before),
    );
  });
});
