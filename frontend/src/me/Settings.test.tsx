import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Settings } from './Settings';
import { pushState, subscribeToPush } from '../pwa/push';
import { isIos, isStandalone } from '../pwa/install';

vi.mock('../pwa/push', () => ({
  pushState: vi.fn(),
  subscribeToPush: vi.fn(),
}));
vi.mock('../pwa/install', () => ({
  isIos: vi.fn(() => false),
  isStandalone: vi.fn(() => true),
}));

const show = () =>
  render(
    <MemoryRouter>
      <Settings />
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.mocked(isIos).mockReturnValue(false);
  vi.mocked(isStandalone).mockReturnValue(true);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('kid settings', () => {
  it('tells an uninstalled iPhone how to add the app to the Home Screen', async () => {
    vi.mocked(pushState).mockResolvedValue('needs-install');
    vi.mocked(isIos).mockReturnValue(true);
    vi.mocked(isStandalone).mockReturnValue(false);
    show();

    expect(await screen.findByText(/Add to Home Screen/)).toBeInTheDocument();
    // the explanation the one-line banner never had room for
    expect(
      screen.getByText(/only work once ChoreKeeper is on your Home Screen/),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /turn on/i })).not.toBeInTheDocument();
    expect(screen.getByText('Running in a browser tab.')).toBeInTheDocument();
  });

  it('gives non-iOS its own install route', async () => {
    vi.mocked(pushState).mockResolvedValue('needs-install');
    vi.mocked(isStandalone).mockReturnValue(false);
    show();

    expect(await screen.findByText(/Install app/)).toBeInTheDocument();
    expect(screen.queryByText(/Share button/)).not.toBeInTheDocument();
  });

  it('offers the turn-on button once the app is installed', async () => {
    vi.mocked(pushState).mockResolvedValue('ready');
    vi.mocked(subscribeToPush).mockResolvedValue('subscribed');
    show();

    fireEvent.click(await screen.findByRole('button', { name: /turn on reminders/i }));

    expect(subscribeToPush).toHaveBeenCalled();
    expect(await screen.findByText(/Reminders are on/)).toBeInTheDocument();
  });

  it('says reminders are already on and offers nothing to press', async () => {
    vi.mocked(pushState).mockResolvedValue('subscribed');
    show();

    expect(await screen.findByText(/Reminders are on/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /turn on/i })).not.toBeInTheDocument();
  });

  it('explains a block instead of offering a dead button', async () => {
    // subscribeToPush cannot recover from a denial
    vi.mocked(pushState).mockResolvedValue('denied');
    show();

    expect(await screen.findByText(/blocked/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /turn on/i })).not.toBeInTheDocument();
  });

  it('says so plainly when the browser cannot do push at all', async () => {
    vi.mocked(pushState).mockResolvedValue('unsupported');
    show();

    expect(await screen.findByText(/can’t send reminders/)).toBeInTheDocument();
  });
});
