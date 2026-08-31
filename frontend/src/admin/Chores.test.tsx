import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { Chores } from './Chores';

function json(body: unknown, status = 200) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const CHORE = {
  id: 'c1',
  title: 'Empty the sink',
  description: '',
  proof_type: 'photo',
  photo_count: 1,
  photo_prompts: [],
  allow_gallery_upload: false,
  prompt_token_enabled: false,
  verification_mode: 'manual',
  verification_rule: null,
  reward_cents: 200,
  penalty_cents: 0,
  late_multiplier: 1,
  due_time: '08:00:00',
  cadence: 'daily',
  assignment_mode: 'fixed',
  fixed_assignee_id: 'k1',
  assignee_ids: [],
  rotation_period: null,
  rotation_anchor_date: null,
  window_open_offset_s: -43200,
  grace_period_s: 900,
  start_date: '2025-01-01',
  end_date: null,
  active: true,
  auto_pass_threshold: 0.85,
  auto_fail_threshold: 0.35,
};

function setup() {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    if (method !== 'GET')
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });

    if (method === 'PATCH') return Promise.resolve(json({ ...CHORE, reward_cents: 500 }));
    if (method === 'DELETE') return Promise.resolve(json(null, 204));
    if (url.includes('/children'))
      return Promise.resolve(json([{ id: 'k1', display_name: 'Alice', is_active: true }]));
    if (url.includes('/chores')) return Promise.resolve(json([CHORE]));
    return Promise.resolve(json([]));
  });

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Chores />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('admin Chores', () => {
  it('opens a prefilled edit form and PATCHes on save', async () => {
    const calls = setup();

    await waitFor(() => expect(screen.getByText('Empty the sink')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Empty the sink'));

    const title = (await screen.findByDisplayValue('Empty the sink')) as HTMLInputElement;
    expect(title).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    const patch = calls.find((c) => c.method === 'PATCH')!;
    expect(patch.url).toMatch(/\/chores\/c1$/); // no ?apply= — saving always regenerates
    expect((patch.body as Record<string, unknown>).fixed_assignee_id).toBe('k1');
  });

  it('deactivates a chore', async () => {
    const calls = setup();
    await waitFor(() => expect(screen.getByText('Empty the sink')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Empty the sink'));
    await screen.findByDisplayValue('Empty the sink');

    fireEvent.click(screen.getByRole('button', { name: /deactivate/i }));
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true));
    expect(calls.find((c) => c.method === 'DELETE')!.url).toContain('/chores/c1');
  });
});
