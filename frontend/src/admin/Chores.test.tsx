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
  chore_kind: 'scheduled',
  standing_on: false,
  standing_tier_id: null,
  standing_since: null,
  title: 'Empty the sink',
  description: '',
  proof_type: 'photo',
  photo_count: 1,
  photo_prompts: [],
  allow_gallery_upload: false,
  verification_mode: 'manual',
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
  outcome_tiers: null,
  start_date: '2025-01-01',
  end_date: null,
  active: true,
  auto_pass_threshold: 0.85,
  auto_fail_threshold: 0.35,
};

const STANDING = {
  ...CHORE,
  id: 'c1',
  title: 'Missing assignments',
  chore_kind: 'standing',
  cadence: 'standing',
  due_time: '00:00:00',
  proof_type: 'none',
  verification_mode: 'manual',
  reward_cents: 0,
  penalty_cents: 0,
  end_date: null,
  geofence: null,
  outcome_tiers: [
    {
      id: 1,
      condition: 'more than one missing assignment',
      outcome_kind: 'text',
      amount_cents: null,
      text: "grounded until it's fixed",
    },
  ],
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
    if (method === 'POST' && url.includes('/duplicate'))
      return Promise.resolve(
        json({ ...CHORE, id: 'c2', title: 'Empty the sink (copy)', active: false }, 201),
      );
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

    // the rule and checklist belong to the vision model, so they appear with an LLM mode
    fireEvent.change(
      screen.getByLabelText('Proof / verification').parentElement!.querySelectorAll('select')[1],
      {
        target: { value: 'llm_auto' },
      },
    );
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
    fireEvent.click(screen.getByRole('button', { name: /add a check/i }));
    fireEvent.change(screen.getByPlaceholderText(/free of dishes/i), {
      target: { value: 'Is the bowl full?' },
    });
    fireEvent.change(screen.getByDisplayValue('photo'), { target: { value: 'acknowledgement' } });
    // The mode select drops back to a value it still offers rather than showing a stale one.
    expect(screen.getByDisplayValue('manual')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true));

    const body = calls.find((c) => c.method === 'POST')!.body as Record<string, unknown>;
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

  it('duplicates a chore and opens the copy for editing', async () => {
    const calls = setup();

    fireEvent.click(await screen.findByLabelText('Duplicate Empty the sink'));

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/chores/c1/duplicate'))).toBe(
        true,
      ),
    );
    // the copy lands in the editor so the parent can vary the one field they wanted
    expect(await screen.findByDisplayValue('Empty the sink (copy)')).toBeInTheDocument();
  });

  it('turns a chore into a one-off and PATCHes a once(...) cadence', async () => {
    const calls = setup();

    fireEvent.click(await screen.findByText('Empty the sink'));
    fireEvent.click(screen.getByLabelText('One-off — a single date'));
    fireEvent.change(screen.getByLabelText(/^Date/), { target: { value: '2026-09-14' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    const body = calls.find((c) => c.method === 'PATCH')!.body as Record<string, unknown>;
    expect(body.cadence).toBe('once(2026-09-14)');
  });

  it('warns when the one-off date has already passed', async () => {
    setup([{ ...CHORE, cadence: 'once(2020-01-01)' }]);

    fireEvent.click(await screen.findByText('Empty the sink'));

    // the cadence text box is replaced by a date picker, already showing the stored date
    expect(screen.getByLabelText(/^Date/)).toHaveValue('2020-01-01');
    expect(screen.queryByLabelText('Cadence')).not.toBeInTheDocument();
    expect(screen.getByText(/already passed/i)).toBeInTheDocument();
  });

  it('adding an outcome hides the flat reward and PATCHes the tiers', async () => {
    const calls = setup();

    fireEvent.click(await screen.findByText('Empty the sink'));
    expect(screen.getByLabelText('Reward / penalty ($)')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Add an outcome' }));
    fireEvent.change(screen.getByLabelText('Condition 1'), {
      target: { value: 'all A grades' },
    });
    fireEvent.change(screen.getByLabelText('Amount 1'), { target: { value: '100' } });

    // a tiered chore's money comes from its tiers, so the flat pair goes away
    expect(screen.queryByLabelText('Reward / penalty ($)')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));

    const body = calls.find((c) => c.method === 'PATCH')!.body as Record<string, unknown>;
    expect(body.outcome_tiers).toEqual([
      {
        id: 1,
        condition: 'all A grades',
        outcome_kind: 'money',
        amount_cents: 10000,
        text: null,
      },
    ]);
    // and the backend's tiered invariants are satisfied before it ever sees the request
    expect(body.reward_cents).toBe(0);
    expect(body.penalty_cents).toBe(0);
    expect(body.verification_mode).toBe('manual');
  });

  it('stores a penalty tier as a negative amount without asking for a minus sign', async () => {
    const calls = setup();

    fireEvent.click(await screen.findByText('Empty the sink'));
    fireEvent.click(screen.getByRole('button', { name: 'Add an outcome' }));
    fireEvent.change(screen.getByLabelText('Condition 1'), {
      target: { value: 'at least one C' },
    });
    fireEvent.change(screen.getByLabelText('Amount 1'), { target: { value: '50' } });
    fireEvent.change(screen.getByLabelText('Reward or penalty 1'), {
      target: { value: 'penalty' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    const body = calls.find((c) => c.method === 'PATCH')!.body as Record<string, unknown>;
    expect((body.outcome_tiers as { amount_cents: number }[])[0].amount_cents).toBe(-5000);
  });

  it('switches a tier to a text outcome and drops its amount', async () => {
    const calls = setup();

    fireEvent.click(await screen.findByText('Empty the sink'));
    fireEvent.click(screen.getByRole('button', { name: 'Add an outcome' }));
    fireEvent.change(screen.getByLabelText('Condition 1'), {
      target: { value: 'more than one missing assignment' },
    });
    fireEvent.change(screen.getByLabelText('Outcome type 1'), { target: { value: 'text' } });
    fireEvent.change(screen.getByLabelText('Outcome text 1'), {
      target: { value: 'grounded until it is fixed' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    const body = calls.find((c) => c.method === 'PATCH')!.body as Record<string, unknown>;
    expect((body.outcome_tiers as Record<string, unknown>[])[0]).toEqual({
      id: 1,
      condition: 'more than one missing assignment',
      outcome_kind: 'text',
      amount_cents: null,
      text: 'grounded until it is fixed',
    });
  });

  it('drops the schedule and proof sections for a standing chore', async () => {
    setup();

    fireEvent.click(await screen.findByRole('button', { name: 'New chore' }));
    expect(screen.getByLabelText(/^Cadence/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Kind'), { target: { value: 'standing' } });

    // no schedule, no proof, no flat money — a standing chore has none of them
    expect(screen.queryByLabelText(/^Cadence/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Due time')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Proof / verification')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Reward / penalty ($)')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Preview' })).not.toBeInTheDocument();
  });

  it('posts a standing chore with a text-only outcome', async () => {
    const calls = setup();

    fireEvent.click(await screen.findByRole('button', { name: 'New chore' }));
    fireEvent.change(screen.getByLabelText('Kind'), { target: { value: 'standing' } });
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Missing work' } });
    fireEvent.change(screen.getByLabelText('Assignee'), { target: { value: 'k1' } });

    fireEvent.click(screen.getByRole('button', { name: 'Add an outcome' }));
    // the money/text switch is gone — a standing chore moves no money
    expect(screen.queryByLabelText('Outcome type 1')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Condition 1'), {
      target: { value: 'more than one missing assignment' },
    });
    fireEvent.change(screen.getByLabelText('Outcome text 1'), {
      target: { value: 'grounded until it is fixed' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true));

    const body = calls.find((c) => c.method === 'POST')!.body as Record<string, unknown>;
    expect(body.chore_kind).toBe('standing');
    expect(body.cadence).toBe('standing');
    expect(body.proof_type).toBe('none');
    expect(body.reward_cents).toBe(0);
    expect((body.outcome_tiers as Record<string, unknown>[])[0]).toEqual({
      id: 1,
      condition: 'more than one missing assignment',
      outcome_kind: 'text',
      amount_cents: null,
      text: 'grounded until it is fixed',
    });
  });

  it('round-trips the grace period and end date the form used to drop', async () => {
    const calls = setup();

    fireEvent.click(await screen.findByText('Empty the sink'));
    fireEvent.change(screen.getByLabelText(/^Grace period/), { target: { value: '45' } });
    fireEvent.change(screen.getByLabelText(/^End date/), { target: { value: '2030-12-31' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    const body = calls.find((c) => c.method === 'PATCH')!.body as Record<string, unknown>;
    expect(body.grace_period_s).toBe(2700);
    expect(body.end_date).toBe('2030-12-31');
  });

  it('keeps an untouched grace period exactly as stored', async () => {
    const calls = setup();

    fireEvent.click(await screen.findByText('Empty the sink'));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    const body = calls.find((c) => c.method === 'PATCH')!.body as Record<string, unknown>;
    expect(body.grace_period_s).toBe(900);
  });

  it('hides the AI rule and checklist under a non-AI verification mode', async () => {
    setup();

    fireEvent.click(await screen.findByText('Empty the sink'));
    // CHORE is proof_type photo but verification_mode manual — nothing reads a rule here
    expect(screen.queryByLabelText(/verification rule/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /add a check/i })).not.toBeInTheDocument();
  });

  it('saves a standing chore unchanged without an error', async () => {
    // The report that started this: open an existing standing chore, click Save, get
    // "[object Object]". An untouched save must simply PATCH.
    const calls = setup([STANDING]);

    fireEvent.click(await screen.findByText('Missing assignments'));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    const body = calls.find((c) => c.method === 'PATCH')!.body as Record<string, unknown>;
    expect(body.cadence).toBe('standing');
    expect(body.outcome_tiers).toEqual(STANDING.outcome_tiers);
    expect(screen.queryByText(/object Object/)).not.toBeInTheDocument();
  });

  it('refuses a half-filled outcome before the request leaves the browser', async () => {
    const calls = setup([STANDING]);

    fireEvent.click(await screen.findByText('Missing assignments'));
    fireEvent.click(screen.getByRole('button', { name: 'Add an outcome' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText(/Finish outcome 2/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === 'PATCH')).toBe(false);
  });

  it('names every unfinished outcome, and saves once they are filled in', async () => {
    const calls = setup([STANDING]);

    fireEvent.click(await screen.findByText('Missing assignments'));
    fireEvent.click(screen.getByRole('button', { name: 'Add an outcome' }));
    fireEvent.change(screen.getByLabelText('Condition 2'), { target: { value: 'skipped class' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    // condition filled but the outcome text is still blank
    expect(await screen.findByText(/Finish outcome 2/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Outcome text 2'), { target: { value: 'no screens' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
  });
});
