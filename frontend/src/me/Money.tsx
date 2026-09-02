import { useAuth } from '../auth/AuthContext';
import { useBalance, useLedger } from '../api/hooks';
import { Card, Spinner } from '../shared/ui';
import { money } from '../shared/format';
import { entryLabel } from '../shared/status';

export function Money() {
  const { me } = useAuth();
  const balance = useBalance(me?.id ?? '');
  const ledger = useLedger(me?.id ?? '');

  if (!me || balance.isLoading || ledger.isLoading) return <Spinner />;

  return (
    <div className="flex flex-col gap-3 pt-2">
      <h1 className="text-xl font-bold">Money</h1>
      <Card>
        <p className="text-sm text-slate-400">Balance</p>
        <p
          className={`text-3xl font-bold ${
            (balance.data?.balance_cents ?? 0) < 0 ? 'text-rose-400' : ''
          }`}
        >
          {money(balance.data?.balance_cents ?? 0)}
        </p>
      </Card>
      <div className="flex flex-col gap-2">
        {/* backend returns oldest-first; show newest at the top */}
        {[...(ledger.data ?? [])].reverse().map((e) => (
          <div key={e.id} className="flex justify-between border-b border-slate-800 py-2 text-sm">
            <div>
              <p>
                {e.reason || entryLabel(e)}
                {/* "Missed chore" alone doesn't say *which* one — name it, like the
                    parent's statement does, so a charge is recognisable. */}
                {e.chore_title && <span className="text-slate-400"> — {e.chore_title}</span>}
              </p>
              <p className="text-xs text-slate-500">
                {new Date(e.created_at).toLocaleDateString()}
                {e.occurrence_due_at &&
                  ` · due ${new Date(e.occurrence_due_at).toLocaleDateString()}`}
              </p>
            </div>
            <span className={e.amount_cents < 0 ? 'text-rose-400' : 'text-emerald-400'}>
              {e.amount_cents > 0 ? '+' : ''}
              {money(e.amount_cents)}
            </span>
          </div>
        ))}
        {(ledger.data ?? []).length === 0 && <p className="text-slate-500">No entries yet.</p>}
      </div>
    </div>
  );
}
