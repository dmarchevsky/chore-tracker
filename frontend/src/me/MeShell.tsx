import { useEffect, useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { useBalance } from '../api/hooks';
import { money } from '../shared/format';
import { startAutoFlush } from '../pwa/offlineQueue';
import { pushState, type PushState } from '../pwa/push';
import { StandingBanner } from './StandingBanner';

const tabs = [
  { to: '/me', label: 'Pending', end: true },
  { to: '/me/complete', label: 'Complete' },
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
        <NavLink to="/me/settings" aria-label="Settings" className="relative p-2 text-slate-400">
          ⚙️
          {(push === 'needs-install' || push === 'ready') && (
            <span aria-hidden className="absolute right-1 top-1 h-2 w-2 rounded-full bg-sky-400" />
          )}
        </NavLink>
      </header>

      <main className="flex-1 px-4 pb-24">
        <div className="mb-3">
          <StandingBanner />
        </div>
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
