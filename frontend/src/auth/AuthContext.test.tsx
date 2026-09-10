import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
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
  const { error, canSwitchAccount, loading } = useAuth();
  if (loading) return <div>loading</div>;
  return (
    <div>
      <span data-testid="error">{error ?? ''}</span>
      <span data-testid="can-switch">{String(canSwitchAccount)}</span>
    </div>
  );
}

const show = () =>
  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );

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
