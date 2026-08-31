import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { useBodyScrollLock } from '../shared/useBodyScrollLock';

const tabs = [
  { to: '/admin', label: 'Inbox', end: true },
  { to: '/admin/history', label: 'History' },
  { to: '/admin/chores', label: 'Chores' },
  { to: '/admin/kids', label: 'Kids' },
  { to: '/admin/money', label: 'Money' },
  { to: '/admin/jobs', label: 'Ops' },
  { to: '/admin/settings', label: 'Settings' },
];

export function AdminShell() {
  const { me, logout } = useAuth();
  // A drawer on a phone, a pinned sidebar from `md` up — one <nav> either way.
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();

  useBodyScrollLock(open);
  // A deep link or the back button changes the route without a click on our links.
  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  return (
    <div className="mx-auto flex min-h-full max-w-6xl">
      {open && (
        <button
          aria-label="Close menu"
          className="fixed inset-0 z-30 bg-black/60 md:hidden"
          onClick={() => setOpen(false)}
        />
      )}

      <nav
        id="admin-nav"
        className={`fixed inset-y-0 left-0 z-40 flex w-60 flex-col gap-1 border-r border-slate-800 bg-slate-900 p-4 transition-transform md:static md:z-auto md:w-48 md:translate-x-0 md:bg-transparent ${
          open ? '' : '-translate-x-full'
        }`}
      >
        <span className="mb-3 px-3 font-bold">ChoreKeeper</span>
        {tabs.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            end={t.end}
            onClick={() => setOpen(false)}
            className={({ isActive }) =>
              `rounded-lg px-3 py-2 text-sm font-medium ${
                isActive ? 'bg-slate-800 text-sky-400' : 'text-slate-400 hover:text-slate-200'
              }`
            }
          >
            {t.label}
          </NavLink>
        ))}
      </nav>

      {/* min-w-0 lets the two-column Inbox/History grids shrink instead of
          overflowing the viewport — a flex child otherwise refuses to go below
          its content width. */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-2 border-b border-slate-800 px-4 py-3">
          <div className="flex items-center gap-3">
            <button
              aria-label="Menu"
              aria-expanded={open}
              aria-controls="admin-nav"
              className="text-slate-300 md:hidden"
              onClick={() => setOpen(true)}
            >
              <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M3 6h18M3 12h18M3 18h18"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              </svg>
            </button>
            <span className="font-bold md:hidden">ChoreKeeper</span>
          </div>
          <button className="text-sm text-slate-400 hover:text-slate-200" onClick={logout}>
            <span className="hidden sm:inline">{me?.display_name} · </span>sign out
          </button>
        </header>
        <main className="min-w-0 flex-1 p-4">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
