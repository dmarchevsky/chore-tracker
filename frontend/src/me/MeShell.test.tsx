import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { MeShell } from './MeShell';
import { pushState } from '../pwa/push';

vi.mock('../pwa/push', () => ({ pushState: vi.fn() }));
vi.mock('../pwa/offlineQueue', () => ({ startAutoFlush: () => () => {} }));
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ me: { id: 'k1', display_name: 'Nika' } }),
}));

function show() {
  const json = (body: unknown) =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input);
    // /chores feeds StandingBanner, which expects a list
    if (url.includes('/chores')) return Promise.resolve(json([]));
    if (url.includes('/balance')) return Promise.resolve(json({ balance_cents: 500 }));
    return Promise.resolve(json([]));
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <MeShell />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('MeShell', () => {
  it('no longer interrupts the chore list with an install banner', async () => {
    vi.mocked(pushState).mockResolvedValue('needs-install');
    show();

    await waitFor(() => expect(screen.getByLabelText('Settings')).toBeInTheDocument());
    expect(screen.queryByText(/Install this app/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Add to Home Screen/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Turn on notifications so you know/)).not.toBeInTheDocument();
  });

  it('points at settings when there is something to turn on', async () => {
    // deleting the banner deletes the only discovery path, so the gear has to say so
    vi.mocked(pushState).mockResolvedValue('needs-install');
    show();

    const gear = await screen.findByLabelText('Settings');
    await waitFor(() => expect(gear.querySelector('span[aria-hidden]')).toBeTruthy());
    expect(gear).toHaveAttribute('href', '/me/settings');
  });

  it('leaves the gear plain once reminders are already on', async () => {
    vi.mocked(pushState).mockResolvedValue('subscribed');
    show();

    const gear = await screen.findByLabelText('Settings');
    await waitFor(() => expect(screen.getByText('Nika', { exact: false })).toBeInTheDocument());
    expect(gear.querySelector('span[aria-hidden]')).toBeNull();
  });
});
