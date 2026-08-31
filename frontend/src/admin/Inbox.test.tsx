import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { Inbox } from './Inbox';

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

const due = new Date().toISOString();

const occurrence = {
  id: 'o1',
  chore_id: 'c1',
  assignee_id: 'k1',
  window_open_at: due,
  due_at: due,
  status: 'submitted',
  was_late: false,
  settlement_locked_at: null,
  reward_cents: 200,
  penalty_cents: 0,
  prompt_token: null,
  verification_error: null,
};

const submission = {
  id: 's1',
  kind: 'photo',
  source: 'camera',
  note: null,
  flags: ['DUPLICATE_SUSPECTED'],
  created_at: due,
  geo_distance_m: null,
  geo_within: null,
  media: [],
};

const verification = {
  id: 'v1',
  kind: 'llm',
  verdict: 'fail',
  confidence: 0.91,
  reasoning: 'flags: DUPLICATE_SUSPECTED; #1:no(0.91)',
  child_message: null,
  checks: [{ id: 1, answer: 'no', confidence: 0.91, evidence: 'this is a drum set, not a dog' }],
  image_quality_issue: 'none',
  created_by: 'system',
  created_at: due,
};

function renderInbox() {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input);
    if (url.includes('inbox=true')) return Promise.resolve(json([occurrence]));
    if (url.includes('/chores'))
      return Promise.resolve(json([{ id: 'c1', title: 'Empty the sink' }]));
    if (url.endsWith('/children')) return Promise.resolve(json([{ id: 'k1', display_name: 'Mo' }]));
    if (url.endsWith('/occurrences/o1')) return Promise.resolve(json(occurrence));
    if (url.includes('/submissions')) return Promise.resolve(json([submission]));
    if (url.includes('/verifications')) return Promise.resolve(json([verification]));
    return Promise.resolve(json([]));
  });

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Inbox />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(renderInbox);
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('admin Inbox', () => {
  it('lists items waiting for review and opens the detail pane', async () => {
    await waitFor(() => expect(screen.getByText('Empty the sink')).toBeInTheDocument());
    screen.getByText('Empty the sink').click();

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^approve$/i })).toBeInTheDocument(),
    );
    expect(screen.getByPlaceholderText(/your kid will see this/i)).toBeInTheDocument();
  });

  it('names the status and the kid instead of printing the raw enum', async () => {
    await waitFor(() => expect(screen.getByText('Empty the sink')).toBeInTheDocument());

    expect(screen.getByText('Checking…')).toBeInTheDocument();
    expect(screen.queryByText('submitted')).not.toBeInTheDocument();
    expect(screen.getByText(/^Mo ·/)).toBeInTheDocument();
  });

  it('leads with why the item is held and what the model actually found', async () => {
    await waitFor(() => expect(screen.getByText('Empty the sink')).toBeInTheDocument());
    screen.getByText('Empty the sink').click();

    // The flag is explained, not shouted as an enum...
    await waitFor(() =>
      expect(screen.getAllByText(/looks like a photo sent before/i).length).toBeGreaterThan(0),
    );
    expect(screen.queryByText(/DUPLICATE_SUSPECTED/)).not.toBeInTheDocument();
    // ...and the model's own justification is on screen, not buried in raw JSON.
    expect(screen.getByText(/drum set, not a dog/i)).toBeInTheDocument();
    expect(screen.getByText(/The AI says: Fail/i)).toBeInTheDocument();
  });
});
