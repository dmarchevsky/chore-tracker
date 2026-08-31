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

const dispute = {
  id: 'd1',
  occurrence_id: 'o1',
  author_user_id: 'k1',
  message: 'I did walk him, the photo is just dark',
  status: 'open',
  status_at_filing: 'rejected',
  resolution_note: null,
  resolved_at: null,
  created_at: due,
  chore_title: 'Empty the sink',
  author_name: 'Mo',
  occurrence_status: 'rejected',
  occurrence_due_at: due,
};

function renderInbox() {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input);
    if (url.includes('inbox=true')) return Promise.resolve(json([occurrence]));
    if (url.includes('/chores'))
      return Promise.resolve(json([{ id: 'c1', title: 'Empty the sink' }]));
    if (url.endsWith('/children')) return Promise.resolve(json([{ id: 'k1', display_name: 'Mo' }]));
    if (url.endsWith('/occurrences/o1')) return Promise.resolve(json(occurrence));
    if (url.includes('/disputes')) return Promise.resolve(json([dispute]));
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

/** The chore title appears in the disputes section too; the queue row is the last one. */
async function queueRow() {
  await waitFor(() => expect(screen.getAllByText('Empty the sink').length).toBeGreaterThan(0));
  return screen.getAllByText('Empty the sink').at(-1)!;
}

describe('admin Inbox', () => {
  it('lists items waiting for review and opens the detail pane', async () => {
    (await queueRow()).click();

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^approve$/i })).toBeInTheDocument(),
    );
    expect(screen.getByPlaceholderText(/^Reason — your kid will see this$/)).toBeInTheDocument();
  });

  it('names the status and the kid instead of printing the raw enum', async () => {
    await queueRow();

    expect(screen.getByText('Checking…')).toBeInTheDocument();
    expect(screen.queryByText('submitted')).not.toBeInTheDocument();
    expect(screen.getAllByText(/^Mo ·/).length).toBeGreaterThan(0);
  });

  it('surfaces a kid’s “this isn’t right” instead of leaving it in a push notification', async () => {
    await waitFor(() =>
      expect(screen.getByText(/Kids say something is wrong \(1\)/)).toBeInTheDocument(),
    );
    expect(screen.getAllByText(/the photo is just dark/).length).toBeGreaterThan(0);

    screen.getByText(/the photo is just dark/).click();
    await waitFor(() =>
      expect(screen.getByPlaceholderText(/reply — your kid will see this/i)).toBeInTheDocument(),
    );
  });

  it('leads with why the item is held and what the model actually found', async () => {
    (await queueRow()).click();

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
