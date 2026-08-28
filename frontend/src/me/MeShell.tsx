import { useEffect, useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { useBalance } from '../api/hooks';
import { money } from '../shared/format';
import { startAutoFlush } from '../pwa/offlineQueue';
import { isIos, isStandalone } from '../pwa/install';
import { pushState, subscribeToPush, type PushState } from '../pwa/push';

const tabs = [
  { to: '/me', label: 'Today', end: true },
  { to: '/me/week', label: 'Week' },
  { to: '/me/history', label: 'History' },
  { to: '/me/money', label: 'Money' },
  { to: '/me/rules', label: 'Rules' },
];

export function MeShell() {
  const { me } = useAuth();
  const balance = useBalance(me!.id);
  const [push, setPush] = useState<PushState>('unsupported');

  useEffect(() => startAutoFlush(), []);
  useEffect(() => {
    void pushState().then(setPush);
  }, []);

  return (
    <div className="mx-auto flex min-h-full max-w-md flex-col">
      <header className="flex items-center justify-between px-4 py-3">
        <div>
          <p className="text-sm text-slate-400">Hi {me!.display_name}</p>
          <p className="text-lg font-bold">
            {balance.data ? money(balance.data.balance_cents) : '—'}
          </p>
        </div>
      </header>

      {push === 'needs-install' && (
        <Banner>
          {isIos()
            ? 'Tap Share → “Add to Home Screen” to get chore reminders.'
            : 'Install this app (browser menu → Install) to get reminders.'}
        </Banner>
      )}
      {push === 'ready' && isStandalone() && (
        <Banner action={() => subscribeToPush().then(setPush)} actionLabel="Turn on">
          Turn on notifications so you know when a chore is due.
        </Banner>
      )}

      <main className="flex-1 px-4 pb-24">
        <Outlet />
      </main>

      <nav className="fixed inset-x-0 bottom-0 mx-auto flex max-w-md justify-around border-t border-slate-800 bg-slate-950/95 pb-[env(safe-area-inset-bottom)]">
        {tabs.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            end={t.end}
            className={({ isActive }) =>
              `flex-1 py-3 text-center text-sm font-medium ${
                isActive ? 'text-sky-400' : 'text-slate-400'
              }`
            }
          >
            {t.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

function Banner({
  children,
  action,
  actionLabel,
}: {
  children: React.ReactNode;
  action?: () => void;
  actionLabel?: string;
}) {
  return (
    <div className="mx-4 mb-2 flex items-center justify-between gap-3 rounded-xl bg-slate-800 px-3 py-2 text-sm">
      <span>{children}</span>
      {action && (
        <button className="shrink-0 font-semibold text-sky-400" onClick={action}>
          {actionLabel}
        </button>
      )}
    </div>
  );
}
