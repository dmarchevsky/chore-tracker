import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { Jobs } from './Jobs';

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const DASHBOARD = {
  scheduler: { last_tick_at: '2025-06-02T09:00:00Z', stale: false },
  queue: { queued: 0 },
  stuck_jobs: 0,
  recent_failures: [],
  checkins: [],
};

function setup(notifications: unknown[]) {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input);
    if (url.includes('/admin/notifications')) return Promise.resolve(json(notifications));
    return Promise.resolve(json(DASHBOARD));
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Jobs />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('the ops notification log', () => {
  it('shows what was sent and to what end', async () => {
    setup([
      {
        kind: 'due_soon',
        title: 'Due soon',
        body: 'Kitchen is due at 8:00 am.',
        status: 'sent',
        created_at: '2025-06-02T09:00:00Z',
      },
    ]);

    expect(await screen.findByText(/due_soon/)).toBeInTheDocument();
    expect(screen.getByText('sent')).toBeInTheDocument();
  });

  it('names the fix when the server has no VAPID keys', async () => {
    // `skipped` is the failure that looks like silence: the app is fine, the pushes are
    // logged, and nothing ever reaches a phone (docs/notifications.md).
    setup([
      {
        kind: 'missed',
        title: 'You missed one',
        body: '',
        status: 'skipped',
        created_at: '2025-06-02T09:00:00Z',
      },
    ]);

    expect(await screen.findByText(/no VAPID keys/)).toBeInTheDocument();
  });

  it('says so plainly when nothing has been sent', async () => {
    setup([]);

    expect(await screen.findByText('Nothing sent yet.')).toBeInTheDocument();
  });
});
