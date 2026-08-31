import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, useAuth } from './auth/AuthContext';
import { Login } from './pages/Login';
import { Spinner } from './shared/ui';
import { MeShell } from './me/MeShell';
import { Pending } from './me/Pending';
import { Complete } from './me/Complete';
import { ChoreView } from './me/ChoreView';
import { Money as KidMoney } from './me/Money';
import { Rules } from './me/Rules';
import { AdminShell } from './admin/AdminShell';
import { Inbox } from './admin/Inbox';
import { Chores } from './admin/Chores';
import { Kids } from './admin/Kids';
import { Money as AdminMoney } from './admin/Money';
import { Jobs } from './admin/Jobs';
import { Settings } from './admin/Settings';

const qc = new QueryClient({
  defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false } },
});

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
          <Route index element={<Pending />} />
          <Route path="complete" element={<Complete />} />
          <Route path="money" element={<KidMoney />} />
          <Route path="rules" element={<Rules />} />
          <Route path="chores/:id" element={<ChoreView />} />
        </Route>
      ) : (
        <Route path="/admin" element={<AdminShell />}>
          <Route index element={<Inbox />} />
          <Route path="review/:id" element={<Inbox />} />
          <Route path="chores" element={<Chores />} />
          <Route path="kids" element={<Kids />} />
          <Route path="money" element={<AdminMoney />} />
          <Route path="jobs" element={<Jobs />} />
          <Route path="settings" element={<Settings />} />
        </Route>
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
