import { NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';

const tabs = [
  { to: '/admin', label: 'Inbox', end: true },
  { to: '/admin/chores', label: 'Chores' },
  { to: '/admin/money', label: 'Kids & money' },
  { to: '/admin/jobs', label: 'Ops' },
];

export function AdminShell() {
  const { me, logout } = useAuth();
  return (
    <div className="mx-auto flex min-h-full max-w-5xl flex-col">
      <header className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <div className="flex items-center gap-6">
          <span className="font-bold">ChoreKeeper</span>
          <nav className="flex gap-4">
            {tabs.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                end={t.end}
                className={({ isActive }) =>
                  `text-sm font-medium ${isActive ? 'text-sky-400' : 'text-slate-400 hover:text-slate-200'}`
                }
              >
                {t.label}
              </NavLink>
            ))}
          </nav>
        </div>
        <button className="text-sm text-slate-400 hover:text-slate-200" onClick={logout}>
          {me?.display_name} · sign out
        </button>
      </header>
      <main className="flex-1 p-4">
        <Outlet />
      </main>
    </div>
  );
}
