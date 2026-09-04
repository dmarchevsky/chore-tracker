import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { PushCard } from './PushCard';
import { pushState, subscribeToPush, unsubscribeFromPush } from './push';
import { isIos } from './install';

vi.mock('./push', () => ({
  pushState: vi.fn(),
  subscribeToPush: vi.fn(),
  unsubscribeFromPush: vi.fn(),
}));
vi.mock('./install', () => ({
  isIos: vi.fn(() => false),
  isStandalone: vi.fn(() => true),
}));

const show = () =>
  render(
    <PushCard
      heading="Reminders"
      pitch="Get a nudge when a chore opens."
      installReason="Reminders only work once ChoreKeeper is on your Home Screen."
    />,
  );

beforeEach(() => vi.mocked(isIos).mockReturnValue(false));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('the notifications card', () => {
  it('tells an uninstalled iPhone how to add the app to the Home Screen', async () => {
    vi.mocked(pushState).mockResolvedValue('needs-install');
    vi.mocked(isIos).mockReturnValue(true);
    show();

    expect(await screen.findByText(/Add to Home Screen/)).toBeInTheDocument();
    // the explanation the one-line banner never had room for
    expect(
      screen.getByText(/only work once ChoreKeeper is on your Home Screen/),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /turn on/i })).not.toBeInTheDocument();
  });

  it('gives non-iOS its own install route', async () => {
    vi.mocked(pushState).mockResolvedValue('needs-install');
    show();

    expect(await screen.findByText(/Install app/)).toBeInTheDocument();
    expect(screen.queryByText(/Share button/)).not.toBeInTheDocument();
  });

  it('offers the turn-on button once the app is installed', async () => {
    vi.mocked(pushState).mockResolvedValue('ready');
    vi.mocked(subscribeToPush).mockResolvedValue('subscribed');
    show();

    fireEvent.click(await screen.findByRole('button', { name: /turn on notifications/i }));

    expect(subscribeToPush).toHaveBeenCalled();
    expect(await screen.findByText(/Notifications are on/)).toBeInTheDocument();
  });

  it('can turn them back off again', async () => {
    // The backend has always had DELETE /push/subscribe; nothing reached it until now, so
    // a device that opted in could never opt out short of revoking the OS permission.
    vi.mocked(pushState).mockResolvedValue('subscribed');
    vi.mocked(unsubscribeFromPush).mockResolvedValue('ready');
    show();

    fireEvent.click(await screen.findByRole('button', { name: /turn off/i }));

    expect(unsubscribeFromPush).toHaveBeenCalled();
    expect(
      await screen.findByRole('button', { name: /turn on notifications/i }),
    ).toBeInTheDocument();
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

    expect(await screen.findByText(/can’t show notifications/)).toBeInTheDocument();
  });
});
