import { useState } from 'react';
import { useAuth } from '../auth/AuthContext';
import { ApiError } from '../api/client';
import { Button, Card } from '../shared/ui';

export function Login() {
  const { login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [totp, setTotp] = useState('');
  const [needTotp, setNeedTotp] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password, totp);
    } catch (err) {
      if (err instanceof ApiError && /totp/i.test(err.message)) {
        setNeedTotp(true);
        setError('Enter the 6-digit code from your authenticator.');
      } else {
        setError(err instanceof ApiError ? err.message : 'Could not sign in');
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-full max-w-sm flex-col justify-center gap-4 p-6">
      <h1 className="text-2xl font-bold">ChoreKeeper</h1>
      <Card>
        <form className="flex flex-col gap-3" onSubmit={submit}>
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
          {needTotp && (
            <>
              <label className="text-sm text-slate-400" htmlFor="t">
                Authenticator code
              </label>
              <input
                id="t"
                inputMode="numeric"
                className="rounded-xl bg-slate-800 p-3 tracking-[0.4em]"
                value={totp}
                onChange={(e) => setTotp(e.target.value)}
              />
            </>
          )}
          {error && <p className="text-sm text-rose-400">{error}</p>}
          <Button type="submit" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>
      </Card>
    </div>
  );
}
