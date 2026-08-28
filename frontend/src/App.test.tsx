import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { App } from './App';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('App shell', () => {
  it('shows the login form when not authenticated', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'not authenticated' }), { status: 401 }),
    );
    render(<App />);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument(),
    );
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
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
