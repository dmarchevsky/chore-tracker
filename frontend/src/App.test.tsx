import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { App } from './App';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('App shell', () => {
  it('offers a retry, not a password form, when Access has not signed anyone in', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'not authenticated' }), { status: 401 }),
    );
    render(<App />);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument(),
    );
    // Sign-in is Google via Cloudflare Access; no credential fields exist by default.
    expect(screen.queryByLabelText(/username/i)).not.toBeInTheDocument();
  });

  it('names the Google account when Access let through a non-member', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: 'stranger@example.com is signed in to Google but is not an active member',
        }),
        { status: 403, headers: { 'content-type': 'application/json' } },
      ),
    );
    render(<App />);
    expect(await screen.findByText(/stranger@example.com/)).toBeInTheDocument();
  });

  it('routes a signed-in child to the kid shell', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          id: '1',
          username: 'alice',
          display_name: 'Alice',
          role: 'child',
          csrf_token: 'x',
          totp_enrolled: false,
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    );
    render(<App />);
    await waitFor(() => expect(screen.getByText(/hi alice/i)).toBeInTheDocument());
  });
});
