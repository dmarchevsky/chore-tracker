import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { Login } from './Login';
import { useAuth } from '../auth/AuthContext';

vi.mock('../auth/AuthContext', () => ({ useAuth: vi.fn() }));

const NOT_A_MEMBER = 'stranger@example.com is signed in to Google but is not an active member';

function setup(error: string | null, canSwitchAccount = error !== null) {
  const logout = vi.fn();
  const refresh = vi.fn();
  vi.mocked(useAuth).mockReturnValue({
    me: null,
    loading: false,
    error,
    canSwitchAccount,
    breakGlassLogin: vi.fn(),
    logout,
    refresh,
  });
  render(<Login />);
  return { logout, refresh };
}

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
});
