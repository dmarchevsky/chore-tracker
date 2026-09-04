import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
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

const show = () =>
  render(
    <MemoryRouter>
      <Settings />
    </MemoryRouter>,
  );

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('kid settings', () => {
  it('offers reminders in the kid’s own words', async () => {
    vi.mocked(pushState).mockResolvedValue('ready');
    show();

    expect(await screen.findByText('Reminders')).toBeInTheDocument();
    expect(screen.getByText(/nudge when a chore opens/)).toBeInTheDocument();
  });

  it('says whether the app is installed', async () => {
    vi.mocked(pushState).mockResolvedValue('needs-install');
    vi.mocked(isStandalone).mockReturnValue(false);
    show();

    expect(await screen.findByText('Running in a browser tab.')).toBeInTheDocument();
  });
});
