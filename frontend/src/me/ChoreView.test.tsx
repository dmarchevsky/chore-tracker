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
  verification_error: null,
};

function renderChore(verdict: Record<string, unknown>) {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input);
    if (url.includes('/verifications')) return Promise.resolve(json([verdict]));
    if (url.includes('/disputes')) return Promise.resolve(json([]));
    if (url.includes('/submissions')) return Promise.resolve(json([]));
    if (url.includes('/occurrences/o1')) return Promise.resolve(json(occurrence));
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
});
