import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { Chores } from './Chores';

// Leaflet needs a layout engine jsdom lacks; the map is a lazy chunk of its own.
vi.mock('./FenceMap', () => ({ default: () => <div data-testid="map" /> }));

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
  geofence: null,
  verification_checklist: null,
  start_date: '2025-01-01',
  end_date: null,
  active: true,
  auto_pass_threshold: 0.85,
  auto_fail_threshold: 0.35,
};

function setup(chores: unknown[] = [CHORE]) {
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
    if (url.includes('/chores')) return Promise.resolve(json(chores));
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

  it('edits the open time in hours before due and PATCHes the offset', async () => {
    const calls = setup();
    await waitFor(() => expect(screen.getByText('Empty the sink')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Empty the sink'));
    await screen.findByDisplayValue('Empty the sink');

    // -43200s is the stored default: 12 hours before an 08:00 due time.
    const opens = screen.getByDisplayValue('12') as HTMLInputElement;
    expect(screen.getByText(/^opens .* the day before/i)).toBeInTheDocument();

    fireEvent.change(opens, { target: { value: '2' } });
    expect(screen.getByText(/^opens .*, the same day/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    expect(
      (calls.find((c) => c.method === 'PATCH')!.body as Record<string, unknown>)
        .window_open_offset_s,
    ).toBe(-7200);
  });

  it('leaves an untouched open time exactly as stored', async () => {
    const calls = setup();
    await waitFor(() => expect(screen.getByText('Empty the sink')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Empty the sink'));
    await screen.findByDisplayValue('Empty the sink');

    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    expect(
      (calls.find((c) => c.method === 'PATCH')!.body as Record<string, unknown>)
        .window_open_offset_s,
    ).toBe(-43200);
  });

  it('offers a geofence editor for location chores and PATCHes the fence', async () => {
    const FENCED = {
      ...CHORE,
      id: 'c2',
      title: 'Arrive at school',
      proof_type: 'location',
      photo_count: 0,
      verification_mode: 'auto_accept',
      geofence: { lat: 37.7749, lon: -122.4194, radius_m: 120, arrive_before: null },
    };
    const calls = setup([CHORE, FENCED]);

    await waitFor(() => expect(screen.getByText('Arrive at school')).toBeInTheDocument());

    // A photo chore has no fence to set...
    fireEvent.click(screen.getByText('Empty the sink'));
    await screen.findByDisplayValue('Empty the sink');
    expect(screen.queryByRole('slider')).not.toBeInTheDocument();

    // ...a location chore does.
    fireEvent.click(screen.getByText('Arrive at school'));
    await screen.findByDisplayValue('Arrive at school');
    expect(screen.getByTestId('map')).toBeInTheDocument();
    expect(screen.getByDisplayValue('37.7749')).toBeInTheDocument();

    fireEvent.change(screen.getByRole('slider'), { target: { value: '300' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    const patch = calls.find((c) => c.method === 'PATCH')!;
    expect((patch.body as Record<string, unknown>).geofence).toMatchObject({
      lat: 37.7749,
      lon: -122.4194,
      radius_m: 300,
    });
  });

  it('sets how many photos, what each shows, and the AI checks', async () => {
    const calls = setup();
    await waitFor(() => expect(screen.getByText('Empty the sink')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Empty the sink'));
    await screen.findByDisplayValue('Empty the sink');

    // One label row per photo, kept in lockstep with the count.
    expect(screen.getAllByPlaceholderText(/sink close-up|wide kitchen/)).toHaveLength(1);
    fireEvent.change(screen.getByLabelText('How many photos'), { target: { value: '2' } });
    expect(screen.getAllByPlaceholderText(/sink close-up|wide kitchen/)).toHaveLength(2);

    fireEvent.change(screen.getByPlaceholderText('sink close-up'), {
      target: { value: 'sink close-up' },
    });
    fireEvent.change(screen.getByPlaceholderText('wide kitchen'), {
      target: { value: 'wide kitchen' },
    });

    fireEvent.click(screen.getByRole('button', { name: /add a check/i }));
    fireEvent.change(screen.getByPlaceholderText(/free of dishes/i), {
      target: { value: 'Is the sink basin free of dishes?' },
    });

    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));

    const body = calls.find((c) => c.method === 'PATCH')!.body as Record<string, unknown>;
    expect(body.photo_count).toBe(2);
    expect(body.photo_prompts).toEqual(['sink close-up', 'wide kitchen']);
    expect(body.verification_checklist).toEqual([
      { id: 1, text: 'Is the sink basin free of dishes?', required: true },
    ]);
  });

  it('hides the photo settings for a chore that sends no photos', async () => {
    const ACK = { ...CHORE, id: 'c3', title: 'Feed the cat', proof_type: 'acknowledgement' };
    setup([ACK]);
    await waitFor(() => expect(screen.getByText('Feed the cat')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Feed the cat'));
    await screen.findByDisplayValue('Feed the cat');

    expect(screen.queryByLabelText('How many photos')).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/allow picking an existing photo/i)).not.toBeInTheDocument();
  });

  // Nothing reads a rule, a checklist or the thresholds without a photo for the model to
  // look at, and the backend rejects an LLM mode for such a chore outright.
  it('hides the AI-only settings for a chore that sends no photos', async () => {
    const ACK = { ...CHORE, id: 'c3', title: 'Feed the cat', proof_type: 'acknowledgement' };
    setup([ACK]);
    await waitFor(() => expect(screen.getByText('Feed the cat')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Feed the cat'));
    await screen.findByDisplayValue('Feed the cat');

    expect(screen.queryByLabelText(/verification rule/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /add a check/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/auto pass \/ fail confidence/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'llm_auto' })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'llm_assist' })).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'manual' })).toBeInTheDocument();
  });

  // The thresholds only mean something once a verdict is banded on confidence (spec §6.3).
  it('shows the thresholds only for an LLM verification mode', async () => {
    setup();
    await waitFor(() => expect(screen.getByText('Empty the sink')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Empty the sink'));
    await screen.findByDisplayValue('Empty the sink');

    expect(screen.queryByLabelText(/auto pass \/ fail confidence/i)).not.toBeInTheDocument();
    fireEvent.change(screen.getByDisplayValue('manual'), { target: { value: 'llm_auto' } });
    expect(screen.getByLabelText(/auto pass \/ fail confidence/i)).toBeInTheDocument();
  });

  it('drops a stale rule and LLM mode when the proof carries no photo', async () => {
    const calls = setup([]);
    await waitFor(() => expect(screen.getByRole('button', { name: /new chore/i })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: /new chore/i }));
    await screen.findByLabelText('Title');

    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Feed the cat' } });
    fireEvent.change(screen.getByDisplayValue('manual'), { target: { value: 'llm_auto' } });
    fireEvent.change(screen.getByLabelText(/verification rule/i), {
      target: { value: 'Is the bowl full?' },
    });
    fireEvent.change(screen.getByDisplayValue('photo'), { target: { value: 'acknowledgement' } });
    // The mode select drops back to a value it still offers rather than showing a stale one.
    expect(screen.getByDisplayValue('manual')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true));

    const body = calls.find((c) => c.method === 'POST')!.body as Record<string, unknown>;
    expect(body.verification_rule).toBeNull();
    expect(body.verification_checklist).toBeNull();
    expect(body.verification_mode).toBe('manual');
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
