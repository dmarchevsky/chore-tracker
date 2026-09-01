import { useState } from 'react';
import { useAuth } from '../auth/AuthContext';
import { ApiError } from '../api/client';
import { Button, Card } from '../shared/ui';

/** Shown only when the automatic Google sign-in did not land on a household member.
 *  In the normal case Cloudflare Access has already signed the visitor in and the app
 *  goes straight to their screens — nobody sees this page. */
export function Login() {
  const { error, refresh } = useAuth();
  const [breakGlass, setBreakGlass] = useState(false);

  if (breakGlass) return <BreakGlassForm onCancel={() => setBreakGlass(false)} />;

  return (
    <div className="mx-auto flex min-h-full max-w-sm flex-col justify-center gap-4 p-6">
      <h1 className="text-2xl font-bold">ChoreKeeper</h1>
      <Card className="flex flex-col gap-3">
        {error ? (
          <>
            <p className="text-sm text-rose-400">{error}</p>
            <p className="text-sm text-slate-400">
              Ask a parent to add that address under Kids — and to the Cloudflare Access policy — or
              sign in with a different Google account.
            </p>
          </>
        ) : (
          <p className="text-sm text-slate-400">You are not signed in.</p>
        )}
        <Button onClick={() => void refresh()}>Try again</Button>
        <a className="text-center text-sm text-slate-400 underline" href="/cdn-cgi/access/logout">
          Sign in as someone else
        </a>
        <button
          type="button"
          className="text-center text-xs text-slate-600 underline"
          onClick={() => setBreakGlass(true)}
        >
          Use the break-glass password
        </button>
      </Card>
    </div>
  );
}

/** The local admin password. Only reachable from inside the house: the tunnel's front
 *  door answers 404 for this path, so submitting from the internet cannot succeed. */
function BreakGlassForm({ onCancel }: { onCancel: () => void }) {
  const { breakGlassLogin } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await breakGlassLogin(username, password);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not sign in');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-full max-w-sm flex-col justify-center gap-4 p-6">
      <h1 className="text-2xl font-bold">Break-glass sign-in</h1>
      <Card>
        <form className="flex flex-col gap-3" onSubmit={submit}>
          <p className="text-sm text-slate-400">
            Parent account only, and only from inside the house.
          </p>
          <label className="text-sm text-slate-400" htmlFor="u">
            Username
          </label>
          <input
            id="u"
            className="rounded-xl bg-slate-800 p-3"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
          <label className="text-sm text-slate-400" htmlFor="p">
            Password
          </label>
          <input
            id="p"
            type="password"
            className="rounded-xl bg-slate-800 p-3"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          {error && <p className="text-sm text-rose-400">{error}</p>}
          <Button type="submit" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </Button>
          <button type="button" className="text-sm text-slate-400 underline" onClick={onCancel}>
            Back
          </button>
        </form>
      </Card>
    </div>
  );
}
