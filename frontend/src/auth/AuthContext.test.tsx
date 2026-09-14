import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, useAuth } from './AuthContext';

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

/** Answer the bootstrap probe with `me`, and the dev-users sniff that follows it with 404. */
function stubProbe(me: Response) {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input);
    if (url.includes('/auth/dev/users')) return Promise.resolve(json(404, { detail: 'Not Found' }));
    return Promise.resolve(me);
  });
}

function Probe() {
  const { error, canSwitchAccount, loading, refresh } = useAuth();
  if (loading) return <div>loading</div>;
  return (
    <div>
      <span data-testid="error">{error ?? ''}</span>
      <span data-testid="can-switch">{String(canSwitchAccount)}</span>
      <button onClick={() => void refresh()}>re-probe</button>
    </div>
  );
}

/** AuthProvider now reads the query client (it clears the cache when the person changes),
 *  so it has to be mounted the way App.tsx mounts it — inside the provider. */
function mount(ui: React.ReactNode, qc = new QueryClient()) {
  return render(
    <QueryClientProvider client={qc}>
      <AuthProvider>{ui}</AuthProvider>
    </QueryClientProvider>,
  );
}

const show = () => mount(<Probe />);

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
});

describe('the sign-in probe', () => {
  it('blames the server, not the account, when the origin cannot check the assertion', async () => {
    // The 2026-09-10 lockout: the api could not reach Cloudflare's JWKS endpoint. Offering
    // to switch Google account there is advice that cannot possibly work.
    stubProbe(json(503, { detail: 'ChoreKeeper cannot reach Cloudflare right now.' }));
    show();

    await waitFor(() =>
      expect(screen.getByTestId('error')).toHaveTextContent('cannot reach Cloudflare'),
    );
    expect(screen.getByTestId('can-switch')).toHaveTextContent('false');
  });

  it('still offers to switch account when Access vouched for a stranger', async () => {
    stubProbe(json(403, { detail: 'nobody@example.com is not an active member' }));
    show();

    await waitFor(() =>
      expect(screen.getByTestId('error')).toHaveTextContent('not an active member'),
    );
    expect(screen.getByTestId('can-switch')).toHaveTextContent('true');
  });

  it('says nothing at all about a plain 401 — that is just "not signed in"', async () => {
    stubProbe(json(401, { detail: 'not authenticated' }));
    show();

    await waitFor(() => expect(screen.getByTestId('can-switch')).toHaveTextContent('false'));
    expect(screen.getByTestId('error')).toHaveTextContent('');
  });
});

describe('the cache when the person changes', () => {
  // Most query keys are not scoped by user — ['chores'], ['inbox'], ['occurrences', …] —
  // and me/Settings.tsx exists precisely because a tablet gets handed between kids.
  const ME = (id: string) => ({ id, role: 'child', csrf_token: 'c' });

  it('drops the previous kid\u2019s data when someone else takes over', async () => {
    // The only way one person's cache can reach another is inside a single document — a
    // reload builds a new QueryClient anyway. So: same provider, second probe, new person.
    const qc = new QueryClient();
    let who = 'k1';
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input);
      if (url.includes('/auth/dev/users')) return Promise.resolve(json(404, {}));
      return Promise.resolve(json(200, ME(who)));
    });

    mount(<Probe />, qc);
    await waitFor(() => expect(screen.getByTestId('can-switch')).toHaveTextContent('false'));
    qc.setQueryData(['chores'], [{ id: 'c1', title: "Kira's chore" }]);

    who = 'k2';
    fireEvent.click(screen.getByRole('button', { name: 're-probe' }));

    await waitFor(() => expect(qc.getQueryData(['chores'])).toBeUndefined());
  });

  it('leaves a cold start alone', async () => {
    // null -> someone is a fresh sign-in: nothing cached belongs to anyone, and clearing
    // resets an already-mounted query to pending without refetching it — a spinner that
    // never resolves.
    stubProbe(json(200, ME('k1')));
    const qc = new QueryClient();
    qc.setQueryData(['chores'], [{ id: 'c1' }]);

    mount(<Probe />, qc);
    await waitFor(() => expect(screen.getByTestId('can-switch')).toHaveTextContent('false'));

    expect(qc.getQueryData(['chores'])).toEqual([{ id: 'c1' }]);
  });

  it('keeps the cache when the same person is re-probed', async () => {
    // A recovered session is not a new person, and clearing there would throw away every
    // screen the parent was looking at for no reason.
    stubProbe(json(200, ME('k1')));
    const qc = new QueryClient();
    const { rerender } = mount(<Probe />, qc);
    await waitFor(() => expect(screen.getByTestId('can-switch')).toHaveTextContent('false'));

    qc.setQueryData(['chores'], [{ id: 'c1' }]);
    rerender(
      <QueryClientProvider client={qc}>
        <AuthProvider>
          <Probe />
        </AuthProvider>
      </QueryClientProvider>,
    );

    await new Promise((r) => setTimeout(r, 20));
    expect(qc.getQueryData(['chores'])).toEqual([{ id: 'c1' }]);
  });
});
