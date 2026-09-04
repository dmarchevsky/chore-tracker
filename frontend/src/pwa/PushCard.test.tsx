import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { PushCard } from './PushCard';
import {
  describeTest,
  pushState,
  sendTestPush,
  subscribeToPush,
  unsubscribeFromPush,
} from './push';
import { isIos } from './install';

vi.mock('./push', async (orig) => ({
  // describeTest is the copy under test in the last block — keep the real one.
  ...(await orig<typeof import('./push')>()),
  pushState: vi.fn(),
  subscribeToPush: vi.fn(),
  unsubscribeFromPush: vi.fn(),
  sendTestPush: vi.fn(),
}));
vi.mock('./install', () => ({
  isIos: vi.fn(() => false),
  isStandalone: vi.fn(() => true),
}));

const show = (offerTest = false) =>
  render(
    <PushCard
      heading="Reminders"
      pitch="Get a nudge when a chore opens."
      installReason="Reminders only work once ChoreKeeper is on your Home Screen."
      offerTest={offerTest}
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

describe('the test-notification button', () => {
  it('is offered only where the caller asked for it', async () => {
    vi.mocked(pushState).mockResolvedValue('subscribed');
    show();

    expect(await screen.findByRole('button', { name: /turn off/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /send a test/i })).not.toBeInTheDocument();
  });

  it.each(['ready', 'denied', 'needs-install', 'unsupported', 'unconfigured'] as const)(
    'is still there when this device is not subscribed (%s)',
    async (state) => {
      // The bug this replaces: the button lived inside the `subscribed` branch, so it was
      // invisible on exactly the devices someone is trying to diagnose. The server can still
      // answer — it knows about its own keys and this parent's other devices.
      vi.mocked(pushState).mockResolvedValue(state);
      show(true);

      expect(
        await screen.findByRole('button', { name: /send a test notification/i }),
      ).toBeInTheDocument();
    },
  );

  it('reports how many devices the server actually reached', async () => {
    vi.mocked(pushState).mockResolvedValue('subscribed');
    vi.mocked(sendTestPush).mockResolvedValue({ status: 'sent', devices: 2, error: null });
    show(true);

    fireEvent.click(await screen.findByRole('button', { name: /send a test/i }));

    expect(await screen.findByText(/Sent to 2 devices/)).toBeInTheDocument();
  });

  it('names the server-side fix rather than blaming the phone', async () => {
    // The failure this button exists for: nothing arrives and the phone looks broken when
    // it is the server that has no keys.
    vi.mocked(pushState).mockResolvedValue('subscribed');
    vi.mocked(sendTestPush).mockResolvedValue({ status: 'skipped', devices: 1, error: null });
    show(true);

    fireEvent.click(await screen.findByRole('button', { name: /send a test/i }));

    expect(await screen.findByText(/no VAPID keys/)).toBeInTheDocument();
  });

  it('says when the request never reached the server at all', async () => {
    vi.mocked(pushState).mockResolvedValue('subscribed');
    vi.mocked(sendTestPush).mockRejectedValue(new Error('could not reach ChoreKeeper'));
    show(true);

    fireEvent.click(await screen.findByRole('button', { name: /send a test/i }));

    expect(await screen.findByText(/could not reach ChoreKeeper/)).toBeInTheDocument();
  });
});

describe('describeTest', () => {
  it('puts the missing server keys ahead of the missing subscription', () => {
    // Both are true on a fresh stack; only one of them blocks everyone at once.
    expect(describeTest({ status: 'skipped', devices: 0, error: null }).text).toMatch(/VAPID/);
  });

  it('surfaces the push service’s own words on a failure', () => {
    const r = describeTest({ status: 'failed', devices: 1, error: 'WebPushException: 403' });
    expect(r.ok).toBe(false);
    expect(r.text).toMatch(/403/);
  });
});

describe('a server with no notification keys', () => {
  it('says so instead of quietly leaving the button where it was', async () => {
    // The failure as it reached a real phone: press "Turn on notifications", get asked for
    // permission, grant it — and the card comes back showing the same button, with nothing
    // to suggest the server was never configured.
    vi.mocked(pushState).mockResolvedValue('ready');
    vi.mocked(subscribeToPush).mockResolvedValue('unconfigured');
    show();

    fireEvent.click(await screen.findByRole('button', { name: /turn on notifications/i }));

    expect(await screen.findByText(/no notification keys/)).toBeInTheDocument();
    expect(screen.getByText(/vapid-keys/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /turn on/i })).not.toBeInTheDocument();
  });
});

describe('when turning notifications on throws', () => {
  it('shows the error instead of greying the button out forever', async () => {
    // The failure as reported from a real iPhone against production: press the button,
    // grant permission, and the button just stays disabled — the rejection skipped the
    // setBusy(false) under it, so only a page reload brought the button back and nothing
    // ever said what went wrong. Safari's own words are the whole diagnosis here.
    vi.mocked(pushState).mockResolvedValue('ready');
    vi.mocked(subscribeToPush).mockRejectedValue(
      Object.assign(new Error('Registration failed - push service error'), {
        name: 'AbortError',
      }),
    );
    show();

    fireEvent.click(await screen.findByRole('button', { name: /turn on notifications/i }));

    expect(await screen.findByText(/AbortError: Registration failed/)).toBeInTheDocument();
    // and the button is usable again, without a reload
    expect(screen.getByRole('button', { name: /turn on notifications/i })).toBeEnabled();
  });

  it('reports a turn-off failure in its own words', async () => {
    vi.mocked(pushState).mockResolvedValue('subscribed');
    vi.mocked(unsubscribeFromPush).mockRejectedValue(new Error('could not reach ChoreKeeper'));
    show();

    fireEvent.click(await screen.findByRole('button', { name: /turn off/i }));

    expect(await screen.findByText(/turn notifications off/)).toBeInTheDocument();
    expect(screen.getByText(/could not reach ChoreKeeper/)).toBeInTheDocument();
  });
});
