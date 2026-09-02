import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ChoreView } from './ChoreView';

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

const occurrence = {
  id: 'o1',
  chore_id: 'c1',
  assignee_id: 'k1',
  window_open_at: '2025-01-01T00:00:00Z',
  due_at: '2025-01-02T00:00:00Z',
  status: 'rejected',
  was_late: false,
  settlement_locked_at: null,
  reward_cents: 200,
  penalty_cents: 0,
  settled_at: null,
  appeal_closes_at: null,
  verification_error: null,
};

function renderChore(verdict: Record<string, unknown>, over: Record<string, unknown> = {}) {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input);
    if (url.includes('/verifications')) return Promise.resolve(json([verdict]));
    if (url.includes('/disputes')) return Promise.resolve(json([]));
    if (url.includes('/submissions')) return Promise.resolve(json([]));
    if (url.includes('/occurrences/o1')) return Promise.resolve(json({ ...occurrence, ...over }));
    if (url.includes('/chores/c1'))
      return Promise.resolve(
        json({
          id: 'c1',
          title: 'Walk the dog',
          description: '',
          proof_type: 'photo',
          photo_count: 1,
          photo_prompts: [],
          allow_gallery_upload: false,
        }),
      );
    return Promise.resolve(json([]));
  });

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/me/chores/o1']}>
        <Routes>
          <Route path="/me/chores/:id" element={<ChoreView />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('kid ChoreView', () => {
  it('shows the parent’s own reason for a rejection, attributed', async () => {
    renderChore({
      verdict: 'fail',
      child_message: 'the sink is still full',
      image_quality_issue: null,
      kind: 'manual',
      created_by: 'user',
      created_at: '2025-01-02T10:00:00Z',
    });

    await waitFor(() => expect(screen.getByText('the sink is still full')).toBeInTheDocument());
    expect(screen.getByText('From a parent')).toBeInTheDocument();
    expect(screen.getByText(/final say/i)).toBeInTheDocument();
    // ...not the canned line it used to fall back to.
    expect(screen.queryByText(/have a look and try again/i)).not.toBeInTheDocument();
  });

  it('falls back to the canned line when no one left a message', async () => {
    renderChore({
      verdict: 'fail',
      child_message: null,
      image_quality_issue: null,
      kind: 'llm',
      created_by: 'system',
      created_at: '2025-01-02T10:00:00Z',
    });

    await waitFor(() => expect(screen.getByText(/have a look and try again/i)).toBeInTheDocument());
    expect(screen.queryByText('From a parent')).not.toBeInTheDocument();
  });

  const soon = () => new Date(Date.now() + 3600_000).toISOString();
  const past = () => new Date(Date.now() - 3600_000).toISOString();

  it('says a miss will cost money before it is settled, and after', async () => {
    renderChore(
      {},
      {
        status: 'missed',
        penalty_cents: 500,
        appeal_closes_at: soon(),
      },
    );

    await waitFor(() =>
      expect(screen.getByText(/unless a parent says otherwise/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/\$5\.00/)).toBeInTheDocument();

    cleanup();
    vi.restoreAllMocks();
    renderChore(
      {},
      {
        status: 'missed',
        penalty_cents: 500,
        settled_at: past(),
        appeal_closes_at: soon(),
      },
    );
    await waitFor(() => expect(screen.getByText(/That cost you \$5\.00/)).toBeInTheDocument());
  });

  it('does not put the raw status on screen when there is no news yet', async () => {
    // An open chore has no verdict and no canned line; the message used to fall through to
    // the status enum, so the kid was shown a big "open".
    renderChore({}, { status: 'open' });

    await screen.findByRole('button', { name: /take a photo/i });
    expect(screen.queryByText('open')).not.toBeInTheDocument();
  });

  it('offers the appeal inside the window and drops it once closed', async () => {
    renderChore({}, { status: 'missed', penalty_cents: 500, appeal_closes_at: soon() });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Dispute' })).toBeInTheDocument(),
    );

    cleanup();
    vi.restoreAllMocks();
    renderChore({}, { status: 'missed', penalty_cents: 500, appeal_closes_at: past() });
    await waitFor(() => expect(screen.getByText(/This one was missed/)).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Dispute' })).not.toBeInTheDocument();
  });
});
