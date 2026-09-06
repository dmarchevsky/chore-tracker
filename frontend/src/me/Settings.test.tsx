import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { Settings } from './Settings';
import { pushState } from '../pwa/push';
import { isStandalone } from '../pwa/install';

// The five PushState branches are exercised in src/pwa/PushCard.test.tsx; what is left for
// the page is that it shows the card at all, with the kid's copy, and reads the install
// state honestly.
vi.mock('../pwa/push', () => ({
  pushState: vi.fn(),
  subscribeToPush: vi.fn(),
  unsubscribeFromPush: vi.fn(),
}));
vi.mock('../pwa/install', () => ({
  isIos: vi.fn(() => false),
  isStandalone: vi.fn(() => true),
}));
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ me: { email: 'alice@example.com' }, logout: vi.fn() }),
}));

const show = () => {
  // The page asks the server which notification categories this kid has; the card itself is
  // covered in src/pwa/NotificationPrefs.test.tsx.
  vi.spyOn(globalThis, 'fetch').mockImplementation(() =>
    Promise.resolve(
      new Response(JSON.stringify({ categories: [{ key: 'due_soon', label: 'Due soon' }] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    ),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Settings />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('kid settings', () => {
  it('offers reminders in the kid’s own words', async () => {
    vi.mocked(pushState).mockResolvedValue('ready');
    show();

    expect(await screen.findByText('Reminders')).toBeInTheDocument();
    expect(screen.getByText(/nudge when a chore opens/)).toBeInTheDocument();
  });

  it('lets a kid pick what to hear about, not just whether to hear anything', async () => {
    vi.mocked(pushState).mockResolvedValue('subscribed');
    show();

    expect(await screen.findByLabelText('Due soon')).toBeChecked();
    expect(screen.getByText(/per person, not per device/)).toBeInTheDocument();
  });

  it('says whether the app is installed', async () => {
    vi.mocked(pushState).mockResolvedValue('needs-install');
    vi.mocked(isStandalone).mockReturnValue(false);
    show();

    expect(await screen.findByText('Running in a browser tab.')).toBeInTheDocument();
  });
});
