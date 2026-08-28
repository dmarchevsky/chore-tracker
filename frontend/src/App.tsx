import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, useAuth } from './auth/AuthContext';
import { Login } from './pages/Login';
import { Spinner } from './shared/ui';
import { MeShell } from './me/MeShell';
import { ChoreList } from './me/ChoreList';
import { ChoreView } from './me/ChoreView';
import { Money } from './me/Money';
import { Rules } from './me/Rules';

const qc = new QueryClient({
  defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false } },
});

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
      {me.role === 'child' ? (
        <Route path="/me" element={<MeShell />}>
          <Route index element={<ChoreList scope="today" title="Today" />} />
          <Route path="week" element={<ChoreList scope="week" title="This week" />} />
          <Route path="history" element={<ChoreList scope="history" title="History" />} />
          <Route path="money" element={<Money />} />
          <Route path="rules" element={<Rules />} />
          <Route path="chores/:id" element={<ChoreView />} />
        </Route>
      ) : (
        <Route path="/admin/*" element={<AdminPlaceholder />} />
      )}
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
