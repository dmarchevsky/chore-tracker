import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { NotificationPrefs } from './NotificationPrefs';

const SETTINGS = {
  categories: [
    { key: 'review', label: 'Chores needing my review' },
    { key: 'completed', label: 'Chores my kids finished' },
  ],
  muted: ['completed'],
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function setup(patch?: () => Response) {
  const calls: unknown[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation((_input, init) => {
    if ((init?.method ?? 'GET') === 'PATCH') {
      const body = JSON.parse(String(init?.body));
      calls.push(body);
      return Promise.resolve(patch ? patch() : json({ ...SETTINGS, muted: body.muted }));
    }
    return Promise.resolve(json(SETTINGS));
  });

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NotificationPrefs />
    </QueryClientProvider>,
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('NotificationPrefs', () => {
  it('shows the categories this account has, on unless muted', async () => {
    setup();

    expect(await screen.findByLabelText('Chores needing my review')).toBeChecked();
    expect(screen.getByLabelText('Chores my kids finished')).not.toBeChecked();
  });

  it('sends the whole muted set when one is switched off', async () => {
    const calls = setup();

    fireEvent.click(await screen.findByLabelText('Chores needing my review'));

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toEqual({ muted: ['completed', 'review'] });
    await waitFor(() =>
      expect(screen.getByLabelText('Chores needing my review')).not.toBeChecked(),
    );
  });

  it('switching one back on drops it from the muted set', async () => {
    const calls = setup();

    fireEvent.click(await screen.findByLabelText('Chores my kids finished'));

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toEqual({ muted: [] });
  });

  it('says so when the save fails, and leaves the switch where the server has it', async () => {
    setup(() => json({ detail: 'not a notification category for this account: review' }, 422));

    fireEvent.click(await screen.findByLabelText('Chores needing my review'));

    expect(await screen.findByText(/not a notification category/)).toBeInTheDocument();
    expect(screen.getByLabelText('Chores needing my review')).toBeChecked();
  });
});
