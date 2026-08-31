import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { History } from './History';
import { historyQs } from './api';

function json(body: unknown, total: number) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json', 'X-Total-Count': String(total) },
  });
}

function occ(id: string, status: string) {
  return {
    id,
    chore_id: 'c1',
    assignee_id: 'k1',
    window_open_at: '2025-01-01T00:00:00Z',
    due_at: '2025-01-02T00:00:00Z',
    status,
    was_late: false,
    settlement_locked_at: null,
    reward_cents: 200,
    penalty_cents: 0,
    prompt_token: null,
    verification_error: null,
  };
}

const urls: string[] = [];

function renderHistory() {
  urls.length = 0;
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input);
    if (/\/occurrences\/[^/?]+$/.test(url)) return Promise.resolve(json(occ('a1', 'approved'), 1));
    if (/\/(submissions|verifications|disputes)$/.test(url)) return Promise.resolve(json([], 0));
    if (url.includes('/occurrences')) {
      urls.push(url);
      return Promise.resolve(json([occ('a1', 'approved'), occ('r1', 'rejected')], 7));
    }
    if (url.includes('/chores')) return Promise.resolve(json([{ id: 'c1', title: 'Kitchen' }], 1));
    if (url.endsWith('/children'))
      return Promise.resolve(json([{ id: 'k1', display_name: 'Mo' }], 1));
    return Promise.resolve(json([], 0));
  });

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <History />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('historyQs', () => {
  it('repeats status so the API ORs them, and always asks newest-first', () => {
    const qs = historyQs({ statuses: ['approved', 'rejected'], limit: 50, offset: 0 });
    expect(qs).toContain('status=approved');
    expect(qs).toContain('status=rejected');
    expect(qs).toContain('order=desc');
  });
});

describe('admin History', () => {
  it('lists decided items a parent can open again', async () => {
    renderHistory();

    // `selector` keeps this off the chore filter's <option>.
    const rows = () => screen.getAllByText('Kitchen', { selector: 'p' });
    await waitFor(() => expect(rows()).toHaveLength(2));
    // Both as a status filter chip and as the row's badge.
    expect(screen.getAllByText('Approved').length).toBe(2);
    expect(screen.getAllByText('Rejected').length).toBe(2);

    fireEvent.click(rows()[0].closest('button')!);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^approve$/i })).toBeInTheDocument(),
    );
  });

  it('filters by kid and widens the window on load more', async () => {
    renderHistory();
    await waitFor(() => expect(urls.length).toBeGreaterThan(0));

    await waitFor(() => expect(screen.getByRole('option', { name: 'Mo' })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Kid'), { target: { value: 'k1' } });
    await waitFor(() => expect(urls.at(-1)).toContain('child=k1'));

    // 2 of 7 loaded, so there is more to fetch.
    screen.getByText(/Load more \(2 of 7\)/).click();
    await waitFor(() => expect(urls.at(-1)).toContain('limit=100'));
  });
});
