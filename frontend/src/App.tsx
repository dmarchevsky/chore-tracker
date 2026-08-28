import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, useAuth } from './auth/AuthContext';
import { Login } from './pages/Login';
import { Spinner } from './shared/ui';

const qc = new QueryClient({
  defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false } },
});

function MePlaceholder() {
  const { me, logout } = useAuth();
  return (
    <div className="p-6">
      <p className="text-lg">Hi {me?.display_name} 👋</p>
      <p className="text-slate-400">Your chores land here (feat/phase5-kid-pwa).</p>
      <button className="mt-4 text-sky-400 underline" onClick={logout}>
        Sign out
      </button>
    </div>
  );
}

function AdminPlaceholder() {
  const { me, logout } = useAuth();
  return (
    <div className="p-6">
      <p className="text-lg">Admin — {me?.display_name}</p>
      <p className="text-slate-400">Review inbox + chores land here (feat/phase5-admin-ui).</p>
      <button className="mt-4 text-sky-400 underline" onClick={logout}>
        Sign out
      </button>
    </div>
  );
}

function Shell() {
  const { me, loading } = useAuth();
  if (loading)
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  if (!me) return <Login />;

  const home = me.role === 'admin' ? '/admin' : '/me';
  return (
    <Routes>
      <Route path="/login" element={<Navigate to={home} replace />} />
      <Route
        path="/me/*"
        element={me.role === 'child' ? <MePlaceholder /> : <Navigate to={home} replace />}
      />
      <Route
        path="/admin/*"
        element={me.role === 'admin' ? <AdminPlaceholder /> : <Navigate to={home} replace />}
      />
      <Route path="*" element={<Navigate to={home} replace />} />
    </Routes>
  );
}

export function App() {
  return (
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <BrowserRouter>
          <Shell />
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
