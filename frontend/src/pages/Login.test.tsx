import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Login } from './Login';
import { useAuth } from '../auth/AuthContext';
import type { DevUser } from '../api/types';

vi.mock('../auth/AuthContext', () => ({ useAuth: vi.fn() }));

const NOT_A_MEMBER = 'stranger@example.com is signed in to Google but is not an active member';

function setup(
  error: string | null,
  canSwitchAccount = error !== null,
  devUsers: DevUser[] | null = null,
) {
  const logout = vi.fn();
  const refresh = vi.fn();
  const devLogin = vi.fn();
  vi.mocked(useAuth).mockReturnValue({
    me: null,
    loading: false,
    error,
    canSwitchAccount,
    devUsers,
    breakGlassLogin: vi.fn(),
    devLogin,
    logout,
    refresh,
  });
  render(<Login />);
  return { logout, refresh, devLogin };
}

const DEV_USERS: DevUser[] = [
  { id: 'u-1', username: 'parent', display_name: 'Parent', role: 'admin' },
  { id: 'u-2', username: 'alice', display_name: 'Alice', role: 'child' },
];

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('Login', () => {
  it('names the Google account Access let through', () => {
    setup(NOT_A_MEMBER);
    expect(screen.getByText(/stranger@example.com/)).toBeInTheDocument();
  });

  it('switches account through logout, not a bare link to the app host', () => {
    // The old /cdn-cgi/access/logout link on the app host answered 200 with a dead
    // Cloudflare page and cleared nothing, so the button has to go through the API,
    // which returns the team-domain URL that actually ends the edge session.
    const { logout } = setup(NOT_A_MEMBER);
    fireEvent.click(screen.getByRole('button', { name: /different google account/i }));
    expect(logout).toHaveBeenCalledOnce();
  });

  it('offers no account switch when nobody is signed in', () => {
    // With no Access session there is nothing to switch away from, and asking the API
    // to end one would simply fail.
    setup(null);
    expect(screen.queryByRole('button', { name: /different google account/i })).toBeNull();
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });

  it('does not offer an account switch when the app was simply unreachable', () => {
    // A network failure sets an error too, but ending the edge session cannot fix it —
    // and the request to do so would fail the same way.
    setup('Could not reach ChoreKeeper. Check your connection, then try again.', false);
    expect(screen.getByText(/could not reach/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /different google account/i })).toBeNull();
  });

  it('reveals the break-glass form on demand', () => {
    setup(null);
    fireEvent.click(screen.getByRole('button', { name: /break-glass/i }));
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
  });

  it('signs in as the picked user on the dev stack', async () => {
    const { devLogin } = setup(null, false, DEV_USERS);
    fireEvent.click(screen.getByRole('button', { name: /alice \(child\)/i }));
    await waitFor(() => expect(devLogin).toHaveBeenCalledWith('u-2'));
  });

  it('offers nothing but the picker on the dev stack', () => {
    // Neither Access nor break-glass exists there, so both would be dead ends: the
    // break-glass route 404s under DEV_AUTH and there is no edge session to retry.
    setup(null, false, DEV_USERS);
    expect(screen.queryByRole('button', { name: /break-glass/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /try again/i })).toBeNull();
  });

  it('falls back to the Access page when the picker is empty', () => {
    // devUsers is null in every deployed configuration — the route does not exist there.
    setup(null, false, null);
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });
});
